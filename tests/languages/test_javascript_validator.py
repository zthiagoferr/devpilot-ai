"""Tests for the JavaScript structural validator."""

from __future__ import annotations

from app.languages.base import ValidationContext
from app.languages.validators.javascript import JavascriptValidator
from tests.fixtures import manual_samples

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


def test_assignment_in_condition_is_high() -> None:
    result = validate(manual_samples.MANUAL_JS_ASSIGNMENT_IN_CONDITION)
    assignments = [
        issue for issue in result.issues if issue.cause == "assignment_in_condition"
    ]

    assert len(assignments) == 1
    assert assignments[0].severity == "high"
    assert assignments[0].line == 2
    assert "'x'" in assignments[0].message


def test_comparison_operators_in_condition_are_not_assignments() -> None:
    source = (
        "let x = 0;\n"
        "if (x === 1) { x += 1; }\n"
        "if (x >= 2) { x -= 1; }\n"
        "while (x != 3) { x = x + 1; }\n"
    )
    result = validate(source)
    assert "assignment_in_condition" not in causes(result)


def test_loop_without_progress_is_medium() -> None:
    result = validate(manual_samples.MANUAL_JS_LOOP_WITHOUT_PROGRESS)
    loops = [
        issue for issue in result.issues if issue.cause == "loop_without_progress"
    ]

    assert len(loops) == 1
    assert loops[0].severity == "medium"
    assert loops[0].line == 1
    assert "'i'" in loops[0].message


def test_progressing_loops_are_silent() -> None:
    source = (
        "for (let i = 0; i < 10; i++) { console.log(i); }\n"
        "for (let i = 10; i > 0; i--) { console.log(i); }\n"
        "for (let i = 0; i <= 10; i += 2) { console.log(i); }\n"
        "for (let i = 0, limit = 10; limit > i; i++) { console.log(i); }\n"
    )
    result = validate(source)
    assert "loop_without_progress" not in causes(result)


def test_loop_with_counter_on_the_right_side_is_checked() -> None:
    source = (
        "let limit = 0;\n"
        "for (let i = 10; limit > i; i--) { console.log(i); }\n"
    )
    result = validate(source)
    loops = [
        issue for issue in result.issues if issue.cause == "loop_without_progress"
    ]

    assert len(loops) == 1
    assert loops[0].severity == "medium"
    assert "'i'" in loops[0].message


def test_while_true_without_exit_is_medium() -> None:
    source = "let value = 1;\nwhile (true) { value = value + 1; }\n"
    result = validate(source)
    loops = [
        issue for issue in result.issues if issue.cause == "loop_without_progress"
    ]

    assert len(loops) == 1
    assert loops[0].severity == "medium"
    assert loops[0].line == 2


def test_while_true_with_break_or_return_is_silent() -> None:
    source = (
        "let value = 1;\n"
        "while (true) {\n"
        "  if (value > 10) { break; }\n"
        "  value = value + 1;\n"
        "}\n"
        "while (true) { return 1; }\n"
    )
    result = validate(source)
    assert "loop_without_progress" not in causes(result)


def test_loose_equality_between_literals_is_low() -> None:
    result = validate(manual_samples.MANUAL_JS_LOOSE_EQUALITY)
    loose = [
        issue for issue in result.issues if issue.cause == "suspicious_loose_equality"
    ]

    assert len(loose) == 1
    assert loose[0].severity == "low"
    assert loose[0].line == 1


def test_loose_equality_between_variables_is_silent() -> None:
    source = (
        "const left = 1;\n"
        "const right = '1';\n"
        "if (left == right) { console.log(left); }\n"
        "if ('a' == 'a') { console.log(left); }\n"
        "if (1 === 1) { console.log(left); }\n"
    )
    result = validate(source)
    assert "suspicious_loose_equality" not in causes(result)


def test_nan_comparison_is_medium() -> None:
    result = validate(manual_samples.MANUAL_JS_NAN_COMPARISON)
    comparisons = [issue for issue in result.issues if issue.cause == "nan_comparison"]

    assert len(comparisons) == 1
    assert comparisons[0].severity == "medium"
    assert comparisons[0].line == 2


def test_undeclared_reference_is_medium() -> None:
    source = "function render() {\n  return missingValue + 1;\n}\nrender();\n"
    result = validate(source)
    references = [
        issue for issue in result.issues if issue.cause == "undeclared_reference"
    ]

    assert len(references) == 1
    assert references[0].severity == "medium"
    assert references[0].line == 2
    assert "missingValue" in references[0].message


def test_undeclared_reference_ignores_declarations_later_in_the_file() -> None:
    source = (
        "function render() {\n"
        "  return laterValue;\n"
        "}\n"
        "const laterValue = 1;\n"
        "render();\n"
    )
    result = validate(source)
    assert "undeclared_reference" not in causes(result)


def test_undeclared_reference_ignores_globals_params_and_members() -> None:
    source = (
        "document.addEventListener('DOMContentLoaded', () => {\n"
        "  const items = [1, 2];\n"
        "  items.map((item) => item * 2).forEach((value) => console.log(value));\n"
        "  console.log(window.innerWidth, Math.max(1, 2), JSON.stringify(items));\n"
        "});\n"
        "class Store {\n"
        "  constructor(seed) { this.seed = seed; }\n"
        "  load() { return this.seed; }\n"
        "}\n"
        "new Store(1).load();\n"
    )
    result = validate(source)
    assert "undeclared_reference" not in causes(result)


def test_undeclared_reference_ignores_destructuring() -> None:
    source = (
        "const { a, b } = require('./module');\n"
        "console.log(a, b);\n"
    )
    result = validate(source)
    assert "undeclared_reference" not in causes(result)


def test_undeclared_reference_ignores_private_fields_and_reexports() -> None:
    source = (
        "class Counter {\n"
        "  #count = 0;\n"
        "  increment() { this.#count += 1; return this.#count; }\n"
        "}\n"
        "new Counter().increment();\n"
        'export { format } from "./format.js";\n'
        'export { parse as read } from "./parse.js";\n'
    )
    result = validate(source)
    assert "undeclared_reference" not in causes(result)


def test_undeclared_reference_still_flags_default_exported_unknown_name() -> None:
    result = validate("export default missing;\n")
    references = [
        issue for issue in result.issues if issue.cause == "undeclared_reference"
    ]

    assert len(references) == 1
    assert "missing" in references[0].message


def test_coverage_metadata_declares_semantic_checks() -> None:
    coverage = validate("const value = 1;\n").metadata["coverage"]

    for check in ("conditions", "loops", "comparisons", "references"):
        assert check in coverage["checks"]
    assert coverage["limitations"]
