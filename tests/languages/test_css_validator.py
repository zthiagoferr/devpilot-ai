"""Tests for the CSS structural validator."""

from __future__ import annotations

from app.languages.base import ValidationContext
from app.languages.validators.css import CssValidator
from tests.fixtures import manual_samples

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


def test_manual_invalid_values_and_mistyped_properties() -> None:
    result = validate(manual_samples.MANUAL_CSS_INVALID_VALUES)
    invalid_values = [
        issue for issue in result.issues if issue.cause == "invalid_value"
    ]
    unknown = [issue for issue in result.issues if issue.cause == "unknown_property"]

    assert len(invalid_values) == 2
    assert all(issue.severity == "medium" for issue in invalid_values)
    messages = " ".join(issue.message for issue in invalid_values)
    assert "invalidcolor" in messages
    assert "notacolor" in messages

    assert len(unknown) == 2
    assert all(issue.severity == "low" for issue in unknown)
    unknown_messages = " ".join(issue.message for issue in unknown)
    assert "colour" in unknown_messages
    assert "widht" in unknown_messages


def test_invalid_color_is_medium() -> None:
    result = validate(".a { color: invalidcolor; }\n")
    invalid = [issue for issue in result.issues if issue.cause == "invalid_value"]

    assert len(invalid) == 1
    assert invalid[0].severity == "medium"
    assert invalid[0].line == 1


def test_valid_color_notations_are_silent() -> None:
    source = (
        ".a {\n"
        "  color: #abc;\n"
        "  border-color: #abcd;\n"
        "  background-color: #aabbcc;\n"
        "  outline-color: #aabbccdd;\n"
        "  text-decoration-color: rgb(0 0 0 / 50%);\n"
        "  caret-color: hsl(120, 50%, 50%);\n"
        "  column-rule-color: Red;\n"
        "  stop-color: transparent;\n"
        "  fill: currentColor;\n"
        "}\n"
    )
    result = validate(source)
    assert "invalid_value" not in causes(result)


def test_invalid_hex_color_is_medium() -> None:
    result = validate(".a { color: #12345; }\n")
    invalid = [issue for issue in result.issues if issue.cause == "invalid_value"]

    assert len(invalid) == 1
    assert "#12345" in invalid[0].message


def test_paint_shorthands_with_keywords_are_silent() -> None:
    source = (
        ".a {\n"
        "  border: 1px solid red;\n"
        "  background: center / cover no-repeat;\n"
        "  text-decoration: underline wavy red;\n"
        "  box-shadow: 0 0 2px black, 0 0 4px rgba(0, 0, 0, 0.5);\n"
        "  background-image: linear-gradient(180deg, #fff 0%, #000 100%);\n"
        "  border-color: red blue;\n"
        "}\n"
    )
    result = validate(source)
    assert "invalid_value" not in causes(result)


def test_global_keywords_custom_properties_and_functions_are_silent() -> None:
    source = (
        ":root { --brand: #1a1a1a; --spacing: 4px; }\n"
        ".a {\n"
        "  color: inherit;\n"
        "  border-color: initial;\n"
        "  background-color: unset;\n"
        "  outline-color: revert;\n"
        "  margin: revert-layer;\n"
        "  color: var(--brand);\n"
        "  width: calc(100% - 10px);\n"
        "  height: clamp(1rem, 2vw, 3rem);\n"
        "  gap: min(1rem, 2vw);\n"
        "  padding: max(1rem, 2vw);\n"
        "  background: url(\"img/background.png\");\n"
        "  --anything: not-a-color at all;\n"
        "}\n"
    )
    result = validate(source)
    assert "invalid_value" not in causes(result)
    assert "invalid_unit" not in causes(result)
    assert "unknown_property" not in causes(result)


def test_vendor_prefixed_properties_are_silent() -> None:
    source = (
        ".a {\n"
        "  -webkit-transform: rotate(10deg);\n"
        "  -moz-user-select: none;\n"
        "  -ms-flex: 1;\n"
        "}\n"
    )
    result = validate(source)
    assert "unknown_property" not in causes(result)


def test_invalid_unit_is_medium() -> None:
    source = (
        ".a {\n"
        "  width: 10deg;\n"
        "  animation-duration: 2px;\n"
        "}\n"
    )
    result = validate(source)
    units = [issue for issue in result.issues if issue.cause == "invalid_unit"]

    assert len(units) == 2
    assert all(issue.severity == "medium" for issue in units)
    assert "deg" in units[0].message
    assert "px" in units[1].message


def test_non_zero_length_without_unit_is_medium() -> None:
    result = validate(".a { width: 10; }\n")
    units = [issue for issue in result.issues if issue.cause == "invalid_unit"]

    assert len(units) == 1
    assert units[0].severity == "medium"
    assert "missing a unit" in units[0].message


def test_valid_units_and_zero_without_unit_are_silent() -> None:
    source = (
        ".a {\n"
        "  width: 50%;\n"
        "  height: 10dvh;\n"
        "  min-height: 5vmin;\n"
        "  margin: 0 auto;\n"
        "  padding: 0 0em 0px 0;\n"
        "  inset: 1ch 2ex 3lh 4rlh;\n"
        "  animation-duration: 200ms;\n"
        "  transition-delay: 1s;\n"
        "  rotate: 0.5turn;\n"
        "  z-index: 5;\n"
        "  order: -1;\n"
        "  opacity: .5;\n"
        "  line-height: 1.5;\n"
        "}\n"
    )
    result = validate(source)
    assert "invalid_unit" not in causes(result)


def test_number_or_length_properties_accept_numbers_percentages_and_lengths() -> None:
    """``line-height`` and ``tab-size`` accept number, percentage, and length."""
    source = (
        ".a {\n"
        "  line-height: 2em;\n"
        "  line-height: 24px;\n"
        "  line-height: 1.5;\n"
        "  line-height: 120%;\n"
        "  tab-size: 4ch;\n"
        "  tab-size: 2;\n"
        "  tab-size: 8px;\n"
        "  tab-size: 120%;\n"
        "}\n"
    )
    result = validate(source)

    assert [issue for issue in result.issues if issue.cause == "invalid_unit"] == []
    # Every value above is valid; only the repeated declarations remain.
    assert causes(result) == ["duplicate_property"] * 6


def test_number_or_length_properties_still_reject_time_and_angle_units() -> None:
    result = validate(".a { line-height: 2s; tab-size: 4deg; }\n")
    units = [issue for issue in result.issues if issue.cause == "invalid_unit"]

    assert len(units) == 2
    assert all(issue.severity == "medium" for issue in units)
    assert "s" in units[0].message
    assert "deg" in units[1].message


def test_modern_at_rules_and_media_values_are_silent() -> None:
    source = (
        "@media (max-width: 600px) {\n"
        "  .a { font-size: 14px; }\n"
        "}\n"
        "@supports (display: grid) {\n"
        "  .a { display: grid; grid-template-columns: repeat(3, 1fr); }\n"
        "}\n"
        "@media (prefers-color-scheme: dark) {\n"
        "  :root { color-scheme: dark; }\n"
        "}\n"
    )
    result = validate(source)
    assert "unknown_property" not in causes(result)
    assert "invalid_unit" not in causes(result)


def test_existing_checks_are_preserved_with_value_checks() -> None:
    source = ".a { color: invalidcolor !important; colour: red; color: blue; }\n"
    result = validate(source)
    result_causes = causes(result)

    assert "invalid_value" in result_causes
    assert "important_usage" in result_causes
    assert "unknown_property" in result_causes
    assert "duplicate_property" in result_causes


def test_coverage_metadata_declares_value_checks() -> None:
    coverage = validate(".a { color: red; }\n").metadata["coverage"]

    for check in ("property_names", "value_types", "colors", "units"):
        assert check in coverage["checks"]
    assert coverage["limitations"]
