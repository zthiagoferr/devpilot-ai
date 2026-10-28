"""Tests for the CSS structural validator."""

from __future__ import annotations

from app.languages.base import ValidationContext
from app.languages.validators.css import CssValidator

VALID_CSS = """@import "theme/base.css";

:root {
  --main-color: #1a1a1a;
}

body {
  color: var(--main-color);
  background: url("img/background.png");
}

@media (max-width: 600px) {
  body {
    font-size: 14px;
  }
}
"""


def validate(source: str, context: ValidationContext | None = None):
    return CssValidator().validate(source, context or ValidationContext())


def causes(result) -> list[str]:
    return [issue.cause for issue in result.issues]


def test_valid_css_has_no_issues() -> None:
    result = validate(VALID_CSS)

    assert result.language == "css"
    assert result.issues == ()
    assert result.score == 100
    assert result.metadata["validator"]["name"] == "css_scanner"


def test_unbalanced_braces_is_critical() -> None:
    result = validate("body { color: red;\n")
    unbalanced = [
        issue for issue in result.issues if issue.cause == "unbalanced_braces"
    ]

    assert len(unbalanced) == 1
    assert unbalanced[0].severity == "critical"
    assert unbalanced[0].line == 1


def test_extra_closing_brace_is_critical() -> None:
    result = validate("body { color: red; }\n}\n")
    unbalanced = [
        issue for issue in result.issues if issue.cause == "unbalanced_braces"
    ]

    assert len(unbalanced) == 1
    assert unbalanced[0].severity == "critical"
    assert unbalanced[0].line == 2


def test_important_usage_is_low_per_occurrence() -> None:
    result = validate("body { color: red !important; margin: 0 ! important; }\n")
    important = [issue for issue in result.issues if issue.cause == "important_usage"]

    assert len(important) == 2
    assert all(issue.severity == "low" for issue in important)


def test_duplicate_property_is_medium() -> None:
    result = validate("body { color: red; color: blue; }\n")
    duplicates = [
        issue for issue in result.issues if issue.cause == "duplicate_property"
    ]

    assert len(duplicates) == 1
    assert duplicates[0].severity == "medium"


def test_unbalanced_parentheses_is_high() -> None:
    result = validate("body { width: calc(100% - 10px; }\n")
    parentheses = [
        issue for issue in result.issues if issue.cause == "unbalanced_parentheses"
    ]

    assert len(parentheses) == 1
    assert parentheses[0].severity == "high"


def test_empty_selector_is_high() -> None:
    result = validate("{ color: red; }\n")
    empty = [issue for issue in result.issues if issue.cause == "empty_selector"]

    assert len(empty) == 1
    assert empty[0].severity == "high"


def test_missing_url_reference_is_high() -> None:
    context = ValidationContext(
        path="css/app.css",
        known_paths=frozenset({"css/app.css"}),
        tree_complete=True,
    )
    result = validate(".hero { background: url('../img/missing.png'); }\n", context)
    missing = [issue for issue in result.issues if issue.cause == "reference_missing"]

    assert len(missing) == 1
    assert missing[0].severity == "high"


def test_resolved_url_reference_is_silent() -> None:
    context = ValidationContext(
        path="css/app.css",
        known_paths=frozenset({"css/app.css", "img/background.png"}),
        tree_complete=True,
    )
    result = validate(
        ".hero { background: url('../img/background.png'); }\n",
        context,
    )
    assert "reference_missing" not in causes(result)


def test_external_url_reference_is_ignored() -> None:
    context = ValidationContext(
        path="css/app.css",
        known_paths=frozenset({"css/app.css"}),
        tree_complete=True,
    )
    result = validate(
        ".hero { background: url('https://cdn.example/bg.png'); }\n",
        context,
    )
    assert "reference_missing" not in causes(result)


def test_import_after_rules_is_medium() -> None:
    source = (
        "body { color: red; }\n"
        '@import "theme/late.css";\n'
    )
    result = validate(source)
    late = [issue for issue in result.issues if issue.cause == "import_after_rules"]

    assert len(late) == 1
    assert late[0].severity == "medium"


def test_comments_and_strings_do_not_affect_structure() -> None:
    source = (
        "/* } { } { */\n"
        '.icon::before { content: "{ }"; }\n'
    )
    result = validate(source)
    assert "unbalanced_braces" not in causes(result)


def test_placeholder_url_is_unknown_instead_of_missing() -> None:
    context = ValidationContext(
        path="css/app.css",
        known_paths=frozenset({"css/app.css"}),
        tree_complete=True,
    )
    result = validate(".hero { background: url(${img}/a.png); }\n", context)

    assert "reference_missing" not in causes(result)
    unknown = [issue for issue in result.issues if issue.cause == "reference_unknown"]
    assert len(unknown) == 1
    assert unknown[0].severity == "info"


def test_drive_qualified_url_is_unknown_instead_of_missing() -> None:
    context = ValidationContext(
        path="css/app.css",
        known_paths=frozenset({"css/app.css"}),
        tree_complete=True,
    )
    result = validate('.hero { background: url("C:/site/a.png"); }\n', context)

    assert "reference_missing" not in causes(result)
    assert "reference_unknown" in causes(result)


def test_crlf_and_bom_do_not_create_false_positives() -> None:
    source = "\ufeff" + VALID_CSS.replace("\n", "\r\n")
    result = validate(source)

    assert result.issues == ()
