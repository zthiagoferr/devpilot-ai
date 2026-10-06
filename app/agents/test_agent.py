import ast
from typing import Any

from app.agents.base import BaseAgent


class TestAgent(BaseAgent):
    """Analyzes Python test code and test structure."""

    __test__ = False

    def __init__(self) -> None:
        super().__init__(
            name="test_agent",
            responsibility="Analyze Python tests and test structure.",
        )

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        project_name = context["project_name"]
        source_code = context["source_code"]

        issues: list[dict[str, Any]] = []

        try:
            tree = ast.parse(source_code)
        except SyntaxError as exc:
            return {
                "agent": self.name,
                "project_name": project_name,
                "score": 0,
                "issues": [
                    {
                        "severity": "critical",
                        "message": exc.msg,
                        "line": exc.lineno,
                    }
                ],
                "summary": "Python test syntax error detected.",
            }

        test_functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]

        assert_count = sum(
            isinstance(node, ast.Assert)
            for node in ast.walk(tree)
        )

        if not test_functions:
            issues.append(
                {
                    "severity": "warning",
                    "message": "No test functions were found.",
                    "line": None,
                }
            )

        if test_functions and assert_count == 0:
            issues.append(
                {
                    "severity": "warning",
                    "message": "Test functions exist but no assert statements were found.",
                    "line": None,
                }
            )

        score = max(0, 100 - (len(issues) * 25))

        return {
            "agent": self.name,
            "project_name": project_name,
            "score": score,
            "issues": issues,
            "summary": (
                f"Found {len(test_functions)} test function(s) "
                f"and {assert_count} assert statement(s)."
            ),
        }