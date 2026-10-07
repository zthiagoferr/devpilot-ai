import asyncio
import inspect
import os
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool


RUN_TESTS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Optional project-relative test file or directory.",
        }
    },
    "additionalProperties": False,
}

RUN_TESTS_METADATA: dict[str, Any] = {
    "name": "run_tests",
    "description": "Run the project test suite with pytest.",
    "input_schema": RUN_TESTS_INPUT_SCHEMA,
}

# A test run must not be allowed to consume an unbounded amount of time.
TEST_TIMEOUT_SECONDS = 120


class RunTestsTool(BaseTool):
    """Runs the project's bounded pytest test suite.

    The command is deliberately fixed.  Callers may select a project-relative
    pytest path, but cannot provide executable names, flags, or shell input.
    """

    name = "run_tests"
    description = "Run the project test suite with pytest."
    input_schema = RUN_TESTS_INPUT_SCHEMA
    schema = RUN_TESTS_INPUT_SCHEMA
    metadata = RUN_TESTS_METADATA

    def __init__(self, project_root: Path) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
        )
        self._project_root = Path(project_root).resolve()

        # Keep these available on the instance as well as the class so the
        # tool can be consumed by registries that inspect instances only.
        self.input_schema = RUN_TESTS_INPUT_SCHEMA
        self.schema = RUN_TESTS_INPUT_SCHEMA
        self.metadata = RUN_TESTS_METADATA

    def get_metadata(self) -> dict[str, Any]:
        """Return the V5 tool metadata without exposing mutable internals."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }

    def get_tool_definition(self) -> dict[str, Any]:
        """Return the registry/API definition for this tool."""
        return self.get_metadata()

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        # Do not include exception text, command lines, environment values, or
        # filesystem details in execution errors.
        return {
            "status": "error",
            "error": {"code": code, "message": message},
            "message": message,
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        test_path = kwargs.get("path")

        if test_path is not None and not isinstance(test_path, str):
            return self._error(
                "invalid_input",
                "The test path must be a string.",
            )

        command = [
            "python",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
        ]

        if test_path:
            target = (self._project_root / test_path).resolve()

            if not target.is_relative_to(self._project_root):
                return self._error(
                    "path_outside_project",
                    "Access outside the project is not allowed.",
                )

            command.append(str(target))

        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self._project_root,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=TEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            try:
                process.kill()  # type: ignore[possibly-undefined]
                await process.communicate()  # type: ignore[possibly-undefined]
            except (AttributeError, OSError):
                pass
            return self._error(
                "timeout",
                "The test suite exceeded its execution time limit.",
            )
        except (OSError, asyncio.CancelledError):
            if isinstance(_, asyncio.CancelledError):
                raise
            return self._error(
                "execution_error",
                "Unable to execute the test suite.",
            )
        except Exception:
            return self._error(
                "execution_error",
                "Unable to execute the test suite.",
            )

        return {
            "status": "completed" if process.returncode == 0 else "failed",
            "return_code": process.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        }


def create_testing_tools(project_root: Path) -> list[BaseTool]:
    """Create the fixed, safe set of testing tools for a project."""
    return [RunTestsTool(project_root=project_root)]


def register_testing_tools(registry: Any, project_root: Path) -> Any:
    """Register only the supported testing tool with a tool registry.

    This helper intentionally has no command or executable argument.  It can
    therefore not be used to turn the registry into an arbitrary command
    runner.
    """
    tool = RunTestsTool(project_root=project_root)

    if isinstance(registry, dict):
        registry[tool.name] = tool
        return registry

    register = getattr(registry, "register", None)
    if register is None:
        register = getattr(registry, "register_tool", None)
    if register is None or not callable(register):
        raise TypeError("registry must provide a register method")

    try:
        parameters = list(inspect.signature(register).parameters.values())
    except (TypeError, ValueError):
        parameters = []

    if len(parameters) >= 2:
        register(tool.name, tool)
    else:
        register(tool)

    return registry
