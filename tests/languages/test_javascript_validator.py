"""Tests for the JavaScript structural validator."""

from __future__ import annotations

from app.languages.base import ValidationContext
from app.languages.validators.javascript import JavascriptValidator

VALID_JS = """const items = [1, 2, 3];
const label = `items: ${items.length}`;

function render(value) {
  if (!value) {
    return "empty";
  } else {
    return value;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  console.log(render(label));
});
"""


def validate(source: str, context: ValidationContext | None = None):
    return JavascriptValidator().validate(source, context or ValidationContext())


def causes(result) -> list[str]:
    return [issue.cause for issue in result.issues]


def test_valid_javascript_has_no_issues() -> None:
    result = validate(VALID_JS)

    assert result.language == "javascript"
    assert result.issues == ()
    assert result.score == 100
    assert result.metadata["validator"]["name"] == "javascript_tokenizer"


def test_unbalanced_delimiters_are_critical() -> None:
    result = validate("function run() { if (true) { return 1; }\n")
    unbalanced = [
        issue for issue in result.issues if issue.cause == "unbalanced_delimiters"
    ]

    assert len(unbalanced) == 1
    assert unbalanced[0].severity == "critical"
    assert unbalanced[0].line == 1


def test_template_literal_is_supported() -> None:
    source = "const message = `hello ${name}`;\nconsole.log(message);\n"
    result = validate(source)
    assert result.issues == ()


def test_unterminated_template_is_high() -> None:
    result = validate("const message = `hello ${name};\n")
    unterminated = [
        issue for issue in result.issues if issue.cause == "unterminated_template"
    ]

    assert len(unterminated) == 1
    assert unterminated[0].severity == "high"


def test_unterminated_string_is_high() -> None:
    result = validate('const message = "hello;\n')
    unterminated = [
        issue for issue in result.issues if issue.cause == "unterminated_string"
    ]

    assert len(unterminated) == 1
    assert unterminated[0].severity == "high"


def test_unterminated_comment_is_high() -> None:
    result = validate("const value = 1; /* unfinished\n")
    unterminated = [
        issue for issue in result.issues if issue.cause == "unterminated_comment"
    ]

    assert len(unterminated) == 1
    assert unterminated[0].severity == "high"


def test_let_redeclaration_is_medium() -> None:
    result = validate("let value = 1;\nlet value = 2;\n")
    redeclarations = [issue for issue in result.issues if issue.cause == "redeclaration"]

    assert len(redeclarations) == 1
    assert redeclarations[0].severity == "medium"
    assert redeclarations[0].line == 2


def test_var_redeclaration_is_info() -> None:
    result = validate("var value = 1;\nvar value = 2;\n")
    redeclarations = [issue for issue in result.issues if issue.cause == "redeclaration"]

    assert len(redeclarations) == 1
    assert redeclarations[0].severity == "info"


def test_function_redeclaration_is_medium() -> None:
    result = validate("function run() {}\nfunction run() {}\n")
    redeclarations = [issue for issue in result.issues if issue.cause == "redeclaration"]

    assert len(redeclarations) == 1
    assert redeclarations[0].severity == "medium"


def test_json_only_is_info() -> None:
    result = validate('{"name": "value", "items": [1, 2]}')
    json_issues = [issue for issue in result.issues if issue.cause == "json_only"]

    assert len(json_issues) == 1
    assert json_issues[0].severity == "info"


def test_else_without_if_is_medium() -> None:
    result = validate("else {\n  console.log('x');\n}\n")
    orphan = [issue for issue in result.issues if issue.cause == "orphan_else"]

    assert len(orphan) == 1
    assert orphan[0].severity == "medium"


def test_double_comma_and_empty_assignment() -> None:
    result = validate("const values = [1,,2];\nlet value = ;\n")
    result_causes = causes(result)

    assert "duplicate_comma" in result_causes
    assert "empty_assignment" in result_causes


def test_regex_literal_braces_are_ignored() -> None:
    result = validate("const pattern = /[{}()]/;\nconst value = 1;\n")
    assert "unbalanced_delimiters" not in causes(result)


def test_runtime_calls_are_never_executed() -> None:
    source = "process.exit(1);\nwhile (true) { }\n"
    result = validate(source)

    assert result.language == "javascript"
    assert isinstance(result.score, int)
    # Reaching this line proves that validation did not terminate the process.
    assert "unbalanced_delimiters" not in causes(result)


def test_debugger_and_eval_are_low() -> None:
    result = validate("debugger;\neval('1 + 1');\n")
    assert "debugger_statement" in causes(result)
    assert "eval_usage" in causes(result)
    assert all(
        issue.severity == "low"
        for issue in result.issues
        if issue.cause in {"debugger_statement", "eval_usage"}
    )


def test_crlf_and_bom_do_not_create_false_positives() -> None:
    source = "\ufeff" + VALID_JS.replace("\n", "\r\n")
    result = validate(source)

    assert result.issues == ()
