from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.analysis import get_analysis_service
from app.api.analysis import router as analysis_router
from app.api.deps import get_token_verifier
from app.main import app
from tests.fake_auth import TEST_TOKEN, FakeTokenVerifier, bearer


client = TestClient(app)


def test_orchestrator_status() -> None:
    response = client.get("/agents/orchestrator")

    assert response.status_code == 200

    data = response.json()

    assert data == {
        "agent": "orchestrator",
        "responsibility": "Coordinate and route tasks to specialized agents.",
        "status": "ready",
    }


def test_code_analysis_endpoint() -> None:
    response = client.post(
        "/agents/code",
        json={
            "project_name": "devpilot-ai",
            "source_code": "def hello():\n    return 'hello'\n",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["agent"] == "code_agent"
    assert data["project_name"] == "devpilot-ai"
    assert data["score"] == 100
    assert data["issues"] == []


def test_orchestrate_full_analysis() -> None:
    response = client.post(
        "/agents/orchestrate",
        json={
            "task": "full_analysis",
            "project_name": "devpilot-ai",
            "source_code": (
                "def test_health():\n"
                '    """Test application health."""\n'
                "    assert True\n"
            ),
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["agent"] == "orchestrator"
    assert data["status"] == "completed"

    assert data["delegated_to"] == [
        "code_agent",
        "test_agent",
        "docs_agent",
        "report_agent",
    ]

    report = data["result"]["report"]

    assert report["agent"] == "report_agent"
    assert report["overall_score"] == 100
    assert report["total_issues"] == 0


def test_orchestrate_rejects_empty_project_name() -> None:
    response = client.post(
        "/agents/orchestrate",
        json={
            "task": "code",
            "project_name": "",
            "source_code": "print('hello')",
        },
    )

    assert response.status_code == 422


def test_orchestrate_rejects_missing_source_code() -> None:
    response = client.post(
        "/agents/orchestrate",
        json={
            "task": "code",
            "project_name": "devpilot-ai",
        },
    )

    assert response.status_code == 422


def test_orchestrate_rejects_unknown_task() -> None:
    response = client.post(
        "/agents/orchestrate",
        json={
            "task": "security",
            "project_name": "devpilot-ai",
            "source_code": "print('hello')",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "No agent available for task: security"
    }


CREATED_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_ID = UUID("22222222-2222-4222-8222-222222222222")
CREATED_AT = datetime(2024, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc)
SECOND_CREATED_AT = datetime(2024, 1, 1, 3, 4, 5, 123456, tzinfo=timezone.utc)


def _record(
    record_id: UUID,
    task: str,
    project_name: str,
    source_code: str,
    created_at: datetime,
) -> dict[str, Any]:
    result = {
        "score": 100,
        "issues": [],
        "summary": "No issues found.",
    }
    return {
        "id": record_id,
        "task": task,
        "project_name": project_name,
        "source_code": source_code,
        "analysis_result": result,
        "result": result,
        "created_at": created_at,
    }


class FakeAnalysisService:
    def __init__(self) -> None:
        self.records = [
            _record(
                CREATED_ID,
                "code_analysis",
                "new-project",
                "def newest():\n    return True\n",
                CREATED_AT,
            ),
            _record(
                SECOND_ID,
                "code_analysis",
                "old-project",
                "def older():\n    return False\n",
                SECOND_CREATED_AT,
            ),
        ]
        self.requested_limits: list[int] = []
        self.created_requests: list[dict[str, Any]] = []
        self.created_user_ids: list[str | None] = []
        self.requested_user_ids: list[str | None] = []

    async def create_analysis(
        self,
        analysis: Any,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if hasattr(analysis, "model_dump"):
            values = analysis.model_dump()
        else:
            values = dict(analysis)
        self.created_requests.append(values)
        self.created_user_ids.append(user_id)
        record = self.records[0].copy()
        record.update(
            {
                "task": values["task"],
                "project_name": values["project_name"],
                "source_code": values["source_code"],
            }
        )
        return record

    async def list_analyses(
        self,
        limit: int = 20,
        *,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.requested_limits.append(limit)
        self.requested_user_ids.append(user_id)
        return sorted(
            self.records,
            key=lambda record: record["created_at"],
            reverse=True,
        )[:limit]

    async def get_analysis(
        self,
        analysis_id: UUID,
        *,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        self.requested_user_ids.append(user_id)
        return next(
            (
                record
                for record in self.records
                if record["id"] == analysis_id
            ),
            None,
        )

    def __getattr__(self, name: str) -> Any:
        if name in {"create", "save"}:
            return self.create_analysis
        if name in {"list", "get_all", "get_recent_analyses"}:
            return self.list_analyses
        if name in {"get", "find_by_id", "get_analysis_by_id"}:
            return self.get_analysis
        raise AttributeError(name)


def _test_client() -> tuple[TestClient, FakeAnalysisService]:
    service = FakeAnalysisService()
    test_app = FastAPI()
    test_app.include_router(analysis_router)
    test_app.dependency_overrides[get_analysis_service] = lambda: service
    # Reads require a verified token; the fake keeps the real wiring (header
    # parsing, ownership plumbing) while removing the Firebase dependency.
    test_app.dependency_overrides[get_token_verifier] = lambda: FakeTokenVerifier()
    return TestClient(test_app, headers=bearer(TEST_TOKEN)), service


def _assert_complete_record(data: dict[str, Any], expected_id: UUID) -> None:
    assert data["id"] == str(expected_id)
    assert data["task"] == "code_analysis"
    assert data["project_name"] in {"new-project", "old-project"}
    assert data["source_code"] in {
        "def newest():\n    return True\n",
        "def older():\n    return False\n",
    }
    assert data["created_at"] in {
        CREATED_AT.isoformat().replace("+00:00", "Z"),
        SECOND_CREATED_AT.isoformat().replace("+00:00", "Z"),
    }
    result_key = "analysis_result" if "analysis_result" in data else "result"
    assert data[result_key] == {
        "score": 100,
        "issues": [],
        "summary": "No issues found.",
    }


def test_create_analysis_serializes_complete_record() -> None:
    test_client, _ = _test_client()

    response = test_client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "new-project",
            "source_code": "def newest():\n    return True\n",
        },
    )

    assert response.status_code == 201
    data = response.json()
    _assert_complete_record(data, CREATED_ID)


def test_create_analysis_passes_dashboard_payload_to_service() -> None:
    test_client, service = _test_client()
    payload = {
        "task": "code_analysis",
        "project_name": "new-project",
        "source_code": "def newest():\n    return True\n",
        "repository_url": "https://github.com/example/repo",
    }

    response = test_client.post("/analyses", json=payload)

    assert response.status_code == 201
    # The request model now also carries the optional multi-language fields
    # (``language``/``file_path``/``protheus_version``/``repository_context``),
    # so ``model_dump()`` includes them with their defaults. The dashboard
    # payload must still be delivered unchanged.
    created = service.created_requests[0]
    assert {key: created[key] for key in payload} == payload


def test_create_analysis_records_the_verified_owner_and_hides_it() -> None:
    """Ownership comes from the token and is never echoed back."""
    test_client, service = _test_client()

    response = test_client.post(
        "/analyses",
        json={
            "task": "code_analysis",
            "project_name": "owned-project",
            "source_code": "def newest():\n    return True\n",
            # A client must not be able to choose (or forge) the owner.
            "user_id": "attacker-controlled",
        },
    )

    assert response.status_code == 201
    assert service.created_user_ids == ["user-1"]
    assert "user_id" not in response.json()


def test_list_and_detail_receive_the_verified_owner() -> None:
    test_client, service = _test_client()

    assert test_client.get("/analyses").status_code == 200
    assert test_client.get(f"/analyses/{CREATED_ID}").status_code == 200

    assert service.requested_user_ids == ["user-1", "user-1"]


def test_list_analyses_uses_default_limit_and_newest_first() -> None:
    test_client, service = _test_client()

    response = test_client.get("/analyses")

    assert response.status_code == 200
    assert service.requested_limits == [20]
    data = response.json()
    assert [item["id"] for item in data] == [str(CREATED_ID), str(SECOND_ID)]
    _assert_complete_record(data[0], CREATED_ID)
    _assert_complete_record(data[1], SECOND_ID)


def test_list_analyses_accepts_valid_limit() -> None:
    test_client, service = _test_client()

    response = test_client.get("/analyses?limit=1")

    assert response.status_code == 200
    assert service.requested_limits == [1]
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == str(CREATED_ID)


def test_list_analyses_accepts_maximum_limit() -> None:
    test_client, service = _test_client()

    response = test_client.get("/analyses?limit=100")

    assert response.status_code == 200
    assert service.requested_limits == [100]
    assert [item["id"] for item in response.json()] == [
        str(CREATED_ID),
        str(SECOND_ID),
    ]


def test_list_analyses_rejects_invalid_limits() -> None:
    test_client, _ = _test_client()

    for limit in (0, -1, 101):
        response = test_client.get(f"/analyses?limit={limit}")
        assert response.status_code == 422


def test_get_analysis_by_uuid() -> None:
    test_client, _ = _test_client()

    response = test_client.get(f"/analyses/{CREATED_ID}")

    assert response.status_code == 200
    _assert_complete_record(response.json(), CREATED_ID)


def test_get_unknown_valid_uuid_returns_not_found() -> None:
    test_client, _ = _test_client()

    response = test_client.get("/analyses/33333333-3333-4333-8333-333333333333")

    assert response.status_code == 404


def test_get_analysis_rejects_malformed_uuid() -> None:
    test_client, _ = _test_client()

    response = test_client.get("/analyses/not-a-uuid")

    assert response.status_code == 422


def test_create_analysis_rejects_missing_required_fields() -> None:
    test_client, _ = _test_client()

    for payload in (
        {"project_name": "demo", "source_code": "print('hello')"},
        {"task": "code_analysis", "source_code": "print('hello')"},
        {"task": "code_analysis", "project_name": "demo"},
        {},
    ):
        response = test_client.post("/analyses", json=payload)
        assert response.status_code == 422


def test_create_analysis_rejects_wrong_field_types() -> None:
    test_client, _ = _test_client()

    for payload in (
        {
            "task": "code_analysis",
            "project_name": 123,
            "source_code": "print('hello')",
        },
        {
            "task": "code_analysis",
            "project_name": "demo",
            "source_code": 123,
        },
        {
            "task": 123,
            "project_name": "demo",
            "source_code": "print('hello')",
        },
    ):
        response = test_client.post("/analyses", json=payload)
        assert response.status_code == 422


def test_create_analysis_rejects_empty_required_strings() -> None:
    test_client, _ = _test_client()

    for payload in (
        {
            "task": "code_analysis",
            "project_name": "",
            "source_code": "print('hello')",
        },
        {
            "task": "code_analysis",
            "project_name": "demo",
            "source_code": "",
        },
        {
            "task": "",
            "project_name": "demo",
            "source_code": "print('hello')",
        },
    ):
        response = test_client.post("/analyses", json=payload)
        assert response.status_code == 422
