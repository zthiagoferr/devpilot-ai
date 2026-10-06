import pytest

from app.agents.report_agent import ReportAgent


@pytest.mark.asyncio
async def test_report_agent_consolidates_results() -> None:
    agent = ReportAgent()

    result = await agent.execute(
        {
            "project_name": "devpilot-ai",
            "analyses": {
                "code": {
                    "score": 100,
                    "issues": [],
                },
                "tests": {
                    "score": 75,
                    "issues": [
                        {
                            "severity": "warning",
                            "message": "Example warning.",
                            "line": None,
                        }
                    ],
                },
                "docs": {
                    "score": 50,
                    "issues": [
                        {
                            "severity": "warning",
                            "message": "Missing documentation.",
                            "line": None,
                        }
                    ],
                },
            },
        }
    )

    assert result["agent"] == "report_agent"
    assert result["project_name"] == "devpilot-ai"
    assert result["overall_score"] == 75
    assert result["total_issues"] == 2
    assert len(result["analyses"]) == 3