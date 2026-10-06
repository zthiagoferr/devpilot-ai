import ast
from typing import Any

from app.agents.base import BaseAgent


class DocsAgent(BaseAgent):
    """Analyzes Python documentation and docstring coverage."""

    def __init__(self) -> None:
        super().__init__(
            name="docs_agent",
            responsibility="Analyze Python documentation and docstrings.",
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
                "summary": "Python syntax error prevented documentation analysis.",
            }

        documentable_nodes = [
            node
            for node in ast.walk(tree)
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
        ]

        documented_nodes = [
            node
            for node in documentable_nodes
            if ast.get_docstring(node)
        ]

        missing_docstrings = len(documentable_nodes) - len(documented_nodes)

        if missing_docstrings:
            issues.append(
                {
                    "severity": "warning",
                    "message": (
                        f"{missing_docstrings} documentable object(s) "
                        "without docstrings."
                    ),
                    "line": None,
                }
            )

        if not documentable_nodes:
            score = 100
        else:
            score = round(
                (len(documented_nodes) / len(documentable_nodes)) * 100
            )

        return {
            "agent": self.name,
            "project_name": project_name,
            "score": score,
            "issues": issues,
            "summary": (
                f"Found {len(documentable_nodes)} documentable object(s); "
                f"{len(documented_nodes)} documented."
            ),
        }