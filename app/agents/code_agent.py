import ast
from typing import Any

from app.agents.base import BaseAgent


class CodeAgent(BaseAgent):
    """Analyzes Python source code structure and syntax."""

    def __init__(self) -> None:
        super().__init__(
            name="code_agent",
            responsibility="Analyze Python code quality and structure.",
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
                "summary": "Python syntax error detected.",
            }

        function_count = sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in ast.walk(tree)
        )

        class_count = sum(
            isinstance(node, ast.ClassDef)
            for node in ast.walk(tree)
        )

        return {
            "agent": self.name,
            "project_name": project_name,
            "score": 100,
            "issues": issues,
            "summary": (
                f"Valid Python code containing "
                f"{function_count} function(s) and "
                f"{class_count} class(es)."
            ),
        }