"""Tests for the restricted Python syntax validator."""

from __future__ import annotations

from app.languages.base import ValidationContext
from app.languages.validators.python import PythonValidator


def test_valid_python_syntax() -> None:
    result = PythonValidator().validate(
        "def run(value):\n    return value + 1\n",
        ValidationContext(path="app/main.py"),
    )

    assert result.language == "python"
    assert result.issues == ()
    assert result.score == 100
    assert result.metadata["validator"]["name"] == "python_ast"


def test_python_syntax_error_has_line_and_column() -> None:
    result = PythonValidator().validate(
        "def run(:\n    pass\n",
        ValidationContext(path="app/main.py"),
    )
    issues = result.issues

    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert issues[0].cause == "python_syntax"
    assert issues[0].line == 1
    assert issues[0].column is not None
    assert issues[0].file == "app/main.py"


def test_python_bom_is_tolerated() -> None:
    result = PythonValidator().validate(
        "\ufeffvalue = 1\n",
        ValidationContext(),
    )
    assert result.issues == ()


def test_python_source_is_parsed_not_executed() -> None:
    source = "import os\n\nos._exit(1)\n"
    result = PythonValidator().validate(source, ValidationContext())
    assert result.issues == ()
