"""API tests for ``/corrections`` using a real SQLite database."""

from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.core.config import Settings
from app.db.models import Base
from app.llm.fake import FakeLLMProvider
from app.services.llm_service import LLMService


BROKEN_PYTHON = "def compute_total(items)\n    return sum(items)\n"
FIXED_PYTHON = "def compute_total(items):\n    return sum(items)\n"


def _payload(corrected: str = FIXED_PYTHON, explanation: str = "Fixed it.") -> str:
    return json.dumps({"corrected_code": corrected, "explanation": explanation})


def _body(analysis_id: str | None = None, **overrides) -> dict:
    body = {
        "analysis_id": analysis_id,
        "file": "src/calc.py",
        "language": "python",
        "source_code": BROKEN_PYTHON,
        "issue": {
            "message": "Python syntax error: expected ':'",
            "severity": "critical",
            "line": 1,
            "code": "python_syntax",
        },
    }
    body.update(overrides)
    return body


@pytest.fixture()
def correction_client(tmp_path, monkeypatch):
    """Return a ``TestClient``, an owned analysis id, and the app object."""
    from app.api.corrections import get_correction_llm
    from app.api.deps import get_token_verifier
    from app.core.config import get_settings
    from app.db import session as db_session

    db_path = tmp_path / "corrections.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    original_module_url = db_session.DATABASE_URL

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    # The API tests are not about throttling: keep the shared process limiter
    # out of the way so the suite stays independent of test ordering.
    monkeypatch.setenv("CORRECTION_RATE_LIMIT_REQUESTS", "1000")
    db_session.DATABASE_URL = database_url
    db_session._engine = None
    db_session._session_factory = None
    get_settings.cache_clear()

    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    analysis_id = uuid4()
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT INTO analyses "
            "(id, task, project_name, source_code, user_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                analysis_id.hex,
                "code_analysis",
                "correction-project",
                BROKEN_PYTHON,
                "user-1",
                "completed",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    from app.main import app
    from tests.fake_auth import TEST_TOKEN, FakeTokenVerifier

    app.dependency_overrides[get_token_verifier] = lambda: FakeTokenVerifier()
    app.dependency_overrides[get_correction_llm] = lambda: LLMService(
        FakeLLMProvider(response=_payload())
    )

    try:
        with TestClient(
            app,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        ) as client:
            yield client, str(analysis_id), app
    finally:
        app.dependency_overrides.pop(get_token_verifier, None)
        app.dependency_overrides.pop(get_correction_llm, None)
        db_session.DATABASE_URL = original_module_url
        db_session._engine = None
        db_session._session_factory = None
        get_settings.cache_clear()


def _create(client: TestClient, analysis_id: str | None = None, **overrides) -> dict:
    response = client.post("/corrections", json=_body(analysis_id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_create_correction_returns_pending_record(correction_client) -> None:
    client, analysis_id, _app = correction_client

    data = _create(client, analysis_id)

    assert data["status"] == "pending"
    assert data["origin"] == "ai"
    assert data["analysis_id"] == analysis_id
    assert data["language"] == "python"
    assert data["file"] == "src/calc.py"
    assert data["issue_ref"] == "python-syntax"
    assert data["original_code"] == BROKEN_PYTHON
    assert data["corrected_code"] == FIXED_PYTHON
    assert data["diff"].startswith("--- a/src/calc.py")
    assert data["post_validation"]["status"] == "passed"
    assert data["post_validation"]["target_resolved"] is True
    assert data["created_at"]
    assert data["decided_at"] is None


def test_create_correction_exposes_additive_post_validation_fields(
    correction_client,
) -> None:
    """The new lists are additive: old clients keep reading the old fields."""
    client, analysis_id, _app = correction_client

    data = _create(client, analysis_id)
    validation = data["post_validation"]

    assert validation["status"] == "passed"
    assert [issue["cause"] for issue in validation["issues_resolved"]] == [
        "python_syntax"
    ]
    assert validation["issues_remaining"] == []
    assert validation["issues_new"] == []
    assert validation["issues_warnings"] == []


def test_create_anonymous_correction_is_allowed(correction_client) -> None:
    _client, analysis_id, app = correction_client
    anonymous = TestClient(app)

    response = anonymous.post("/corrections", json=_body())

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"


def test_create_is_unavailable_without_a_configured_provider(
    correction_client,
) -> None:
    from app.api.corrections import get_correction_llm, get_settings

    client, analysis_id, app = correction_client
    app.dependency_overrides.pop(get_correction_llm, None)

    def fake_settings() -> Settings:
        return Settings(
            _env_file=None,
            llm_provider="fake",
            correction_fake_provider_enabled=False,
        )

    app.dependency_overrides[get_settings] = fake_settings
    try:
        response = client.post("/corrections", json=_body(analysis_id))
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides[get_correction_llm] = lambda: LLMService(
            FakeLLMProvider(response=_payload())
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "AI correction is not configured on this server."


def test_create_rejects_unknown_language(correction_client) -> None:
    client, analysis_id, _app = correction_client

    response = client.post(
        "/corrections",
        json=_body(analysis_id, language="cobol"),
    )

    assert response.status_code == 422


def test_create_rejects_oversized_source(correction_client) -> None:
    from app.api.corrections import get_settings

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        llm_provider="fake",
        correction_max_source_bytes=10,
    )
    try:
        response = client.post("/corrections", json=_body(analysis_id))
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 413


def test_create_rejects_foreign_analysis(correction_client) -> None:
    client, _analysis_id, _app = correction_client

    response = client.post("/corrections", json=_body(str(uuid4())))

    assert response.status_code == 404
    assert response.json()["detail"] == "Analysis not found"


def test_get_and_list_require_authentication(correction_client) -> None:
    _client, analysis_id, app = correction_client
    anonymous = TestClient(app)

    assert anonymous.get(f"/corrections/{uuid4()}").status_code == 401
    assert anonymous.get(
        "/corrections",
        params={"analysis_id": analysis_id},
    ).status_code == 401


def test_list_and_get_return_the_callers_correction(correction_client) -> None:
    client, analysis_id, _app = correction_client
    created = _create(client, analysis_id)

    listing = client.get("/corrections", params={"analysis_id": analysis_id})
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [created["id"]]

    detail = client.get(f"/corrections/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == created["id"]


def test_other_user_cannot_read_the_correction(correction_client) -> None:
    from tests.fake_auth import OTHER_TEST_TOKEN

    client, analysis_id, app = correction_client
    created = _create(client, analysis_id)

    other = TestClient(
        app,
        headers={"Authorization": f"Bearer {OTHER_TEST_TOKEN}"},
    )

    assert other.get(f"/corrections/{created['id']}").status_code == 404
    assert other.get(
        "/corrections",
        params={"analysis_id": analysis_id},
    ).status_code == 404


def test_decision_flow(correction_client) -> None:
    client, analysis_id, _app = correction_client
    created = _create(client, analysis_id)

    approved = client.post(
        f"/corrections/{created['id']}/decision",
        json={"status": "approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_at"]

    again = client.post(
        f"/corrections/{created['id']}/decision",
        json={"status": "approved"},
    )
    assert again.status_code == 200
    assert again.json()["decided_at"] == approved.json()["decided_at"]

    conflicting = client.post(
        f"/corrections/{created['id']}/decision",
        json={"status": "rejected"},
    )
    assert conflicting.status_code == 409


def test_export_corrected_is_byte_for_byte(correction_client) -> None:
    client, analysis_id, _app = correction_client
    created = _create(client, analysis_id)

    response = client.get(f"/corrections/{created['id']}/export")

    assert response.status_code == 200
    assert response.content == created["corrected_code"].encode("utf-8")
    assert response.headers["content-type"].startswith("text/plain")
    assert "calc.py" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_export_diff_and_json(correction_client) -> None:
    client, analysis_id, _app = correction_client
    created = _create(client, analysis_id)

    diff = client.get(
        f"/corrections/{created['id']}/export",
        params={"format": "diff"},
    )
    assert diff.status_code == 200
    assert diff.headers["content-type"].startswith("text/x-diff")
    assert diff.text.startswith("--- a/src/calc.py")

    payload = client.get(
        f"/corrections/{created['id']}/export",
        params={"format": "json"},
    )
    assert payload.status_code == 200
    assert payload.headers["content-type"].startswith("application/json")
    data = json.loads(payload.content)
    assert data["id"] == created["id"]
    assert data["corrected_code"] == FIXED_PYTHON


def test_invalid_export_format_is_rejected(correction_client) -> None:
    client, analysis_id, _app = correction_client
    created = _create(client, analysis_id)

    response = client.get(
        f"/corrections/{created['id']}/export",
        params={"format": "zip"},
    )

    assert response.status_code == 422


def test_invalid_provider_response_is_a_502(correction_client) -> None:
    from app.api.corrections import get_correction_llm

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_correction_llm] = lambda: LLMService(
        FakeLLMProvider(response="not a json payload")
    )

    response = client.post("/corrections", json=_body(analysis_id))

    assert response.status_code == 502
    assert response.json()["detail"] == "The AI provider returned an invalid response."


def test_safety_rejection_is_a_422(correction_client) -> None:
    from app.api.corrections import get_correction_llm

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_correction_llm] = lambda: LLMService(
        FakeLLMProvider(
            response=_payload(
                FIXED_PYTHON,
                explanation="The corrected file compiles successfully.",
            )
        )
    )

    response = client.post("/corrections", json=_body(analysis_id))

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "The proposed correction was rejected by safety checks."
    )


def test_incomplete_provider_response_is_a_502(correction_client) -> None:
    from app.api.corrections import get_correction_llm
    from app.llm.base import IncompleteLLMResponseError

    class IncompleteProvider(FakeLLMProvider):
        async def generate(self, prompt, *, system_prompt=None):
            raise IncompleteLLMResponseError("incomplete")

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_correction_llm] = lambda: LLMService(
        IncompleteProvider()
    )

    response = client.post("/corrections", json=_body(analysis_id))

    assert response.status_code == 502
    assert response.json()["detail"] == "The AI provider returned an invalid response."


def test_slow_provider_is_a_504(correction_client) -> None:
    import asyncio

    from app.api.corrections import get_correction_llm, get_settings

    class SlowProvider(FakeLLMProvider):
        async def generate(self, prompt, *, system_prompt=None):
            await asyncio.sleep(0.2)
            return await super().generate(prompt, system_prompt=system_prompt)

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_correction_llm] = lambda: LLMService(
        SlowProvider(response=_payload())
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        llm_provider="fake",
        llm_timeout_seconds=0.01,
    )
    try:
        response = client.post("/corrections", json=_body(analysis_id))
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides[get_correction_llm] = lambda: LLMService(
            FakeLLMProvider(response=_payload())
        )

    assert response.status_code == 504
    assert response.json()["detail"] == (
        "The AI provider timed out. Try a smaller file or try again."
    )


# ---------------------------------------------------- Fase D: modo full (D1)
VALID_PYTHON = "value = 1\n"


def test_create_full_correction_derives_baseline_targets(correction_client) -> None:
    client, analysis_id, _app = correction_client

    response = client.post(
        "/corrections",
        json=_body(analysis_id, mode="full", issue=None),
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["issue_ref"] == "full:1"
    assert data["status"] == "pending"
    assert data["post_validation"]["status"] == "passed"
    assert [issue["cause"] for issue in data["post_validation"]["issues_resolved"]] == [
        "python_syntax"
    ]


def test_create_full_correction_accepts_explicit_issues(correction_client) -> None:
    client, analysis_id, _app = correction_client

    response = client.post(
        "/corrections",
        json=_body(
            analysis_id,
            mode="full",
            issue=None,
            issues=[
                {
                    "message": "Python syntax error: expected ':'",
                    "severity": "critical",
                    "line": 1,
                    "code": "python_syntax",
                },
                {
                    "message": "Second heuristic problem",
                    "severity": "low",
                    "line": 2,
                },
            ],
        ),
    )

    assert response.status_code == 201, response.text
    assert response.json()["issue_ref"] == "full:2"


def test_create_single_correction_still_requires_an_issue(correction_client) -> None:
    client, analysis_id, _app = correction_client

    response = client.post(
        "/corrections",
        json=_body(analysis_id, mode="single", issue=None),
    )

    assert response.status_code == 422


def test_create_rejects_an_invalid_mode(correction_client) -> None:
    client, analysis_id, _app = correction_client

    response = client.post(
        "/corrections",
        json=_body(analysis_id, mode="invalid"),
    )

    assert response.status_code == 422


def test_create_full_correction_rejects_too_many_issues(correction_client) -> None:
    client, analysis_id, _app = correction_client

    response = client.post(
        "/corrections",
        json=_body(
            analysis_id,
            mode="full",
            issue=None,
            issues=[
                {"message": f"Problem {index}", "severity": "low", "line": index}
                for index in range(1, 12)
            ],
        ),
    )

    assert response.status_code == 422
    assert "Too many issues" in response.json()["detail"]


def test_create_full_correction_without_targets_is_422(correction_client) -> None:
    from app.api.corrections import get_correction_llm
    from app.llm.fake import FakeLLMProvider
    from app.services.llm_service import LLMService

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_correction_llm] = lambda: LLMService(
        FakeLLMProvider(response=_payload("value = 2\n"))
    )
    try:
        response = client.post(
            "/corrections",
            json=_body(
                analysis_id,
                source_code=VALID_PYTHON,
                mode="full",
                issue=None,
            ),
        )
    finally:
        app.dependency_overrides[get_correction_llm] = lambda: LLMService(
            FakeLLMProvider(response=_payload())
        )

    assert response.status_code == 422
    assert "No issues to correct" in response.json()["detail"]


def test_create_full_correction_invalid_provider_response_is_502(
    correction_client,
) -> None:
    from app.api.corrections import get_correction_llm
    from app.llm.fake import FakeLLMProvider
    from app.services.llm_service import LLMService

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_correction_llm] = lambda: LLMService(
        FakeLLMProvider(response="not a json payload")
    )

    response = client.post(
        "/corrections",
        json=_body(analysis_id, mode="full", issue=None),
    )

    assert response.status_code == 502


def test_create_full_correction_slow_provider_is_504(correction_client) -> None:
    import asyncio

    from app.api.corrections import get_correction_llm, get_settings
    from app.core.config import Settings
    from app.llm.fake import FakeLLMProvider
    from app.services.llm_service import LLMService

    class SlowProvider(FakeLLMProvider):
        async def generate(self, prompt, *, system_prompt=None):
            await asyncio.sleep(0.2)
            return await super().generate(prompt, system_prompt=system_prompt)

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_correction_llm] = lambda: LLMService(
        SlowProvider(response=_payload())
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        llm_provider="fake",
        llm_timeout_seconds=0.01,
    )
    try:
        response = client.post(
            "/corrections",
            json=_body(analysis_id, mode="full", issue=None),
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides[get_correction_llm] = lambda: LLMService(
            FakeLLMProvider(response=_payload())
        )

    assert response.status_code == 504


def test_create_full_correction_rejects_oversized_source(correction_client) -> None:
    from app.api.corrections import get_settings

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        llm_provider="fake",
        correction_max_source_bytes=10,
    )
    try:
        response = client.post(
            "/corrections",
            json=_body(analysis_id, mode="full", issue=None),
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 413


# --------------------------------------------------- Fase D2a: lote (batch)
def _batch_file(
    path: str,
    source: str = BROKEN_PYTHON,
    issues: list[dict] | None = None,
) -> dict:
    return {
        "path": path,
        "source_code": source,
        "issues": issues
        if issues is not None
        else [
            {
                "message": "Python syntax error: expected ':'",
                "severity": "critical",
                "line": 1,
                "code": "python_syntax",
            }
        ],
    }


def _batch_body(
    analysis_id: str | None = None,
    *,
    files: list[dict] | None = None,
    **overrides,
) -> dict:
    body = {
        "analysis_id": analysis_id,
        "files": files
        if files is not None
        else [_batch_file(f"src/f{index}.py") for index in range(3)],
        "language": "python",
    }
    body.update(overrides)
    return body


def test_batch_three_files_returns_consolidated_results(correction_client) -> None:
    client, analysis_id, _app = correction_client
    files = [_batch_file(f"src/f{index}.py") for index in range(3)]

    response = client.post(
        "/corrections/batch",
        json=_batch_body(analysis_id, files=files),
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["files_total"] == 3
    assert data["files_completed"] == 3
    assert data["files_failed"] == 0
    assert data["files_skipped"] == 0
    assert data["partial"] is False
    assert data["budget_exceeded"] is False
    assert data["issues_resolved_total"] == 3
    assert data["issues_remaining_total"] == 0
    assert data["issues_new_total"] == 0
    assert [item["path"] for item in data["results"]] == [
        "src/f0.py",
        "src/f1.py",
        "src/f2.py",
    ]
    assert all(item["status"] == "completed" for item in data["results"])
    assert all(item["reason"] is None for item in data["results"])
    ids = {item["correction"]["id"] for item in data["results"]}
    assert len(ids) == 3
    for item in data["results"]:
        correction = item["correction"]
        assert correction["file"] == item["path"]
        assert correction["diff"].startswith(f"--- a/{item['path']}")
        assert correction["status"] == "pending"

    listing = client.get("/corrections", params={"analysis_id": analysis_id})
    assert listing.status_code == 200
    assert len(listing.json()) == 3


def test_batch_accepts_exactly_the_configured_maximum(correction_client) -> None:
    client, _analysis_id, _app = correction_client
    files = [_batch_file(f"src/f{index}.py") for index in range(3)]

    response = client.post("/corrections/batch", json=_batch_body(files=files))

    assert response.status_code == 200, response.text


def test_batch_rejects_more_than_the_configured_maximum(correction_client) -> None:
    client, _analysis_id, _app = correction_client
    files = [_batch_file(f"src/f{index}.py") for index in range(4)]

    response = client.post("/corrections/batch", json=_batch_body(files=files))

    assert response.status_code == 422
    assert "Too many files" in response.json()["detail"]


def test_batch_rejects_an_empty_file_list(correction_client) -> None:
    client, _analysis_id, _app = correction_client

    response = client.post("/corrections/batch", json=_batch_body(files=[]))

    assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    ["../etc/passwd", "/etc/passwd", "src/bad\x00name.py", "C:\\repo\\app.py"],
)
def test_batch_rejects_unsafe_paths(correction_client, path: str) -> None:
    client, _analysis_id, _app = correction_client

    response = client.post(
        "/corrections/batch",
        json=_batch_body(files=[_batch_file(path)]),
    )

    assert response.status_code == 422, response.text


def test_batch_rejects_an_unsupported_extension(correction_client) -> None:
    client, _analysis_id, _app = correction_client

    response = client.post(
        "/corrections/batch",
        json=_batch_body(files=[_batch_file("src/program.rb")]),
    )

    assert response.status_code == 422
    assert "Unsupported file type" in response.json()["detail"]


def test_batch_rejects_an_unknown_language(correction_client) -> None:
    client, _analysis_id, _app = correction_client

    response = client.post(
        "/corrections/batch",
        json=_batch_body(
            files=[_batch_file("src/f0.py")],
            language="cobol",
        ),
    )

    assert response.status_code == 422


def test_batch_rejects_a_foreign_analysis(correction_client) -> None:
    client, _analysis_id, _app = correction_client

    response = client.post(
        "/corrections/batch",
        json=_batch_body(str(uuid4()), files=[_batch_file("src/f0.py")]),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Analysis not found"


def test_batch_rejects_an_analysis_reference_without_authentication(
    correction_client,
) -> None:
    _client, analysis_id, app = correction_client

    with TestClient(app) as anonymous:
        response = anonymous.post(
            "/corrections/batch",
            json=_batch_body(analysis_id, files=[_batch_file("src/f0.py")]),
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Analysis not found"


def test_batch_is_unavailable_without_a_configured_provider(
    correction_client,
) -> None:
    from app.api.corrections import get_correction_llm, get_settings

    client, _analysis_id, app = correction_client
    app.dependency_overrides.pop(get_correction_llm, None)

    def fake_settings() -> Settings:
        return Settings(
            _env_file=None,
            llm_provider="fake",
            correction_fake_provider_enabled=False,
        )

    app.dependency_overrides[get_settings] = fake_settings
    try:
        response = client.post(
            "/corrections/batch",
            json=_batch_body(files=[_batch_file("src/f0.py")]),
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides[get_correction_llm] = lambda: LLMService(
            FakeLLMProvider(response=_payload())
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "AI correction is not configured on this server."


def test_batch_sensitive_file_fails_without_aborting_the_other_files(
    correction_client,
) -> None:
    client, _analysis_id, _app = correction_client
    files = [
        {"path": ".env", "source_code": "TOKEN=do-not-send\n", "issues": []},
        _batch_file("src/f0.py"),
    ]

    response = client.post("/corrections/batch", json=_batch_body(files=files))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["files_completed"] == 1
    assert data["files_failed"] == 1
    assert data["partial"] is True
    sensitive = data["results"][0]
    assert sensitive["status"] == "failed"
    assert sensitive["reason"] == "sensitive_file"
    assert sensitive["error_status"] == 422
    assert "do-not-send" not in (sensitive["error_detail"] or "")
    assert data["results"][1]["status"] == "completed"


def test_batch_oversized_file_fails_alone(correction_client) -> None:
    from app.api.corrections import get_settings

    client, _analysis_id, app = correction_client
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        llm_provider="fake",
        correction_max_source_bytes=30,
    )
    try:
        response = client.post(
            "/corrections/batch",
            json=_batch_body(
                files=[_batch_file("src/large.py", "x = 1\n" * 8)]
            ),
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["files_failed"] == 1
    assert data["files_completed"] == 0
    assert data["results"][0]["reason"] == "source_too_large"
    assert data["results"][0]["error_status"] == 413


def test_single_and_full_routes_still_work_with_the_batch_route(
    correction_client,
) -> None:
    client, analysis_id, _app = correction_client

    single = client.post("/corrections", json=_body(analysis_id))
    assert single.status_code == 201

    full = client.post(
        "/corrections",
        json=_body(analysis_id, mode="full", issue=None),
    )
    assert full.status_code == 201


def test_create_full_correction_rejects_an_oversized_explanation(
    correction_client,
) -> None:
    from app.api.corrections import get_correction_llm, get_settings
    from app.llm.fake import FakeLLMProvider
    from app.services.llm_service import LLMService

    client, analysis_id, app = correction_client
    app.dependency_overrides[get_correction_llm] = lambda: LLMService(
        FakeLLMProvider(response=_payload(FIXED_PYTHON, "x" * 100))
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        llm_provider="fake",
        correction_max_explanation_bytes=10,
    )
    try:
        response = client.post(
            "/corrections",
            json=_body(analysis_id, mode="full", issue=None),
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides[get_correction_llm] = lambda: LLMService(
            FakeLLMProvider(response=_payload())
        )

    assert response.status_code == 502
