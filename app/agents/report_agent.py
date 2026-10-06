from typing import Any

from app.agents.base import BaseAgent


class ReportAgent(BaseAgent):
    """Consolidates specialized agent results into a final report."""

    def __init__(self) -> None:
        super().__init__(
            name="report_agent",
            responsibility="Consolidate analysis results into a final report.",
        )

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        project_name = context["project_name"]
        analyses = context["analyses"]

        if not analyses:
            return {
                "agent": self.name,
                "project_name": project_name,
                "overall_score": 0,
                "total_issues": 0,
                "analyses": {},
                "summary": "No analysis results were provided.",
            }

        scores = [
            analysis["score"]
            for analysis in analyses.values()
        ]

        total_issues = sum(
            len(analysis["issues"])
            for analysis in analyses.values()
        )

        overall_score = round(sum(scores) / len(scores))

        return {
            "agent": self.name,
            "project_name": project_name,
            "overall_score": overall_score,
            "total_issues": total_issues,
            "analyses": analyses,
            "summary": (
                f"Analysis completed with an overall score of "
                f"{overall_score}/100 and {total_issues} issue(s) found."
            ),
        }