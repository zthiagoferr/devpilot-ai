from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_orchestrator_status() -> None:
    response = client.get("/agents/orchestrator")

    assert response.status_code == 200

    data = response.json()

    assert data == {
        "agent": "orchestrator",
        "responsibility": "Coordinate and route analysis tasks.",
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
