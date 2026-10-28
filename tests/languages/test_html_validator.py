"""Tests for the HTML structural validator."""

from __future__ import annotations

from app.languages.base import ValidationContext
from app.languages.validators.html import HtmlValidator

VALID_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <h1>Title</h1>
  <img src="logo.png" alt="Logo">
  <label for="name">Name</label>
  <input id="name" type="text">
</body>
</html>
"""


def validate(source: str, context: ValidationContext | None = None):
    return HtmlValidator().validate(source, context or ValidationContext())


def causes(result) -> list[str]:
    return [issue.cause for issue in result.issues]


def test_valid_html_has_no_issues() -> None:
    result = validate(VALID_HTML)

    assert result.language == "html"
    assert result.issues == ()
    assert result.score == 100
    assert result.metadata["validator"]["name"] == "html_parser"


def test_duplicate_ids_are_medium() -> None:
    source = (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta name='viewport' content='width=device-width'></head><body>"
        "<div id='same'></div><div id='same'></div>"
        "</body></html>"
    )
    result = validate(source)
    duplicates = [issue for issue in result.issues if issue.cause == "duplicate_id"]

    assert len(duplicates) == 1
    assert duplicates[0].severity == "medium"


def test_image_without_alt_is_medium() -> None:
    result = validate(VALID_HTML.replace(' alt="Logo"', ""))
    missing = [issue for issue in result.issues if issue.cause == "missing_alt"]

    assert len(missing) == 1
    assert missing[0].severity == "medium"


def test_empty_alt_is_allowed() -> None:
    result = validate(VALID_HTML.replace(' alt="Logo"', ' alt=""'))
    assert "missing_alt" not in causes(result)


def test_input_without_label_is_medium() -> None:
    source = VALID_HTML.replace('<label for="name">Name</label>\n  ', "")
    result = validate(source)
    missing = [issue for issue in result.issues if issue.cause == "missing_label"]

    assert len(missing) == 1
    assert missing[0].severity == "medium"


def test_input_with_aria_label_is_allowed() -> None:
    source = VALID_HTML.replace(
        '<label for="name">Name</label>\n  ',
        "",
    ).replace('id="name"', 'id="name" aria-label="Name"')
    result = validate(source)
    assert "missing_label" not in causes(result)


def test_input_with_wrapping_label_is_allowed() -> None:
    source = (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta name='viewport' content='width=device-width'></head><body>"
        "<label>Name <input type='text'></label>"
        "</body></html>"
    )
    result = validate(source)
    assert "missing_label" not in causes(result)


def test_missing_viewport_is_low() -> None:
    source = VALID_HTML.replace(
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n',
        "",
    )
    result = validate(source)
    viewport = [issue for issue in result.issues if issue.cause == "missing_viewport"]

    assert len(viewport) == 1
    assert viewport[0].severity == "low"


def test_missing_doctype_and_skeleton() -> None:
    result = validate("<p>fragment</p>")
    result_causes = causes(result)

    assert "missing_doctype" in result_causes
    assert "missing_html_tag" in result_causes
    assert "missing_head_tag" in result_causes
    assert "missing_body_tag" in result_causes


def test_missing_lang_is_low() -> None:
    source = VALID_HTML.replace(' lang="en"', "")
    result = validate(source)
    missing = [issue for issue in result.issues if issue.cause == "missing_lang"]

    assert len(missing) == 1
    assert missing[0].severity == "low"


def test_unclosed_tag_is_high() -> None:
    source = VALID_HTML.replace("</h1>", "")
    result = validate(source)
    unclosed = [issue for issue in result.issues if issue.cause == "unclosed_tag"]

    assert len(unclosed) == 1
    assert unclosed[0].severity == "high"
    assert unclosed[0].line == 7


def test_unexpected_closing_tag_is_high() -> None:
    source = VALID_HTML.replace("</body>", "</div></body>")
    result = validate(source)
    unexpected = [
        issue for issue in result.issues if issue.cause == "unexpected_closing_tag"
    ]

    assert len(unexpected) == 1
    assert unexpected[0].severity == "high"


def test_missing_reference_when_tree_is_complete() -> None:
    source = VALID_HTML.replace(
        "</head>",
        '  <link rel="stylesheet" href="css/app.css">\n</head>',
    )
    context = ValidationContext(
        path="index.html",
        known_paths=frozenset({"index.html", "logo.png"}),
        tree_complete=True,
    )
    result = validate(source, context)
    missing = [issue for issue in result.issues if issue.cause == "reference_missing"]

    assert len(missing) == 1
    assert missing[0].severity == "high"
    assert missing[0].line == 5


def test_resolved_reference_is_silent() -> None:
    source = VALID_HTML.replace(
        "</head>",
        '  <link rel="stylesheet" href="css/app.css">\n</head>',
    )
    context = ValidationContext(
        path="index.html",
        known_paths=frozenset({"index.html", "logo.png", "css/app.css"}),
        tree_complete=True,
    )
    result = validate(source, context)
    assert "reference_missing" not in causes(result)
    assert "reference_unknown" not in causes(result)


def test_external_reference_is_ignored() -> None:
    source = VALID_HTML.replace(
        "</head>",
        '  <link rel="stylesheet" href="https://cdn.example/app.css">\n</head>',
    )
    context = ValidationContext(
        path="index.html",
        known_paths=frozenset({"index.html", "logo.png"}),
        tree_complete=True,
    )
    result = validate(source, context)
    assert "reference_missing" not in causes(result)


def test_unknown_reference_when_tree_is_incomplete() -> None:
    source = VALID_HTML.replace(
        "</head>",
        '  <link rel="stylesheet" href="css/app.css">\n</head>',
    )
    context = ValidationContext(
        path="index.html",
        known_paths=frozenset({"index.html", "logo.png"}),
        tree_complete=False,
    )
    result = validate(source, context)
    unknown = [issue for issue in result.issues if issue.cause == "reference_unknown"]

    assert len(unknown) == 1
    assert unknown[0].severity == "info"


def test_no_reference_issues_without_repository_context() -> None:
    source = VALID_HTML.replace(
        "</head>",
        '  <link rel="stylesheet" href="does-not-exist.css">\n</head>',
    )
    result = validate(source)
    assert "reference_missing" not in causes(result)


def test_placeholder_reference_is_unknown_instead_of_missing() -> None:
    source = VALID_HTML.replace(
        "</head>",
        '  <link rel="stylesheet" href="{{ base }}/style.css">\n</head>',
    )
    context = ValidationContext(
        path="index.html",
        known_paths=frozenset({"index.html", "logo.png"}),
        tree_complete=True,
    )
    result = validate(source, context)

    assert "reference_missing" not in causes(result)
    unknown = [issue for issue in result.issues if issue.cause == "reference_unknown"]
    assert len(unknown) == 1
    assert unknown[0].severity == "info"


def test_drive_qualified_reference_is_unknown_instead_of_missing() -> None:
    source = VALID_HTML.replace(
        "</head>",
        '  <link rel="stylesheet" href="C:\\site\\style.css">\n</head>',
    )
    context = ValidationContext(
        path="index.html",
        known_paths=frozenset({"index.html", "logo.png"}),
        tree_complete=True,
    )
    result = validate(source, context)

    assert "reference_missing" not in causes(result)
    assert "reference_unknown" in causes(result)


def test_paragraph_is_implicitly_closed_by_a_block_element() -> None:
    source = (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta name='viewport' content='width=device-width'></head><body>"
        "<p>texto<div>x</div>"
        "</body></html>"
    )
    result = validate(source)

    assert "unclosed_tag" not in causes(result)


def test_paragraph_still_open_at_eof_remains_high() -> None:
    source = (
        "<!DOCTYPE html><html lang='en'><head>"
        "<meta name='viewport' content='width=device-width'></head><body>"
        "<p>ainda aberto"
        "</body></html>"
    )
    result = validate(source)
    unclosed = [issue for issue in result.issues if issue.cause == "unclosed_tag"]

    assert len(unclosed) == 1
    assert "'<p>'" in unclosed[0].message
    assert unclosed[0].severity == "high"


def test_crlf_and_bom_do_not_create_false_positives() -> None:
    source = "\ufeff" + VALID_HTML.replace("\n", "\r\n")
    result = validate(source)

    assert result.issues == ()
