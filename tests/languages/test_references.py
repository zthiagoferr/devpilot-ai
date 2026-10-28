"""Tests for reference extraction and repository-path classification."""

from __future__ import annotations

import pytest

from app.languages.references import (
    classify_reference,
    iter_advpl_includes,
    iter_css_references,
    iter_html_references,
    normalize_repo_path,
)


def test_normalize_relative_reference() -> None:
    assert (
        normalize_repo_path("src/pages/index.html", "../styles/app.css")
        == "src/styles/app.css"
    )


def test_normalize_absolute_reference_is_repo_relative() -> None:
    assert normalize_repo_path("src/pages/index.html", "/assets/logo.png") == (
        "assets/logo.png"
    )


def test_normalize_strips_query_and_fragment() -> None:
    assert normalize_repo_path("index.html", "css/app.css?v=2#top") == "css/app.css"


def test_normalize_decodes_url_encoding() -> None:
    assert normalize_repo_path("index.html", "images/my%20photo.png") == (
        "images/my photo.png"
    )


def test_normalize_rejects_traversal_outside_root() -> None:
    assert normalize_repo_path("src/pages/index.html", "../../../etc/passwd") is None


def test_normalize_allows_traversal_that_stays_inside_root() -> None:
    assert normalize_repo_path("src/pages/index.html", "../../app.css") == "app.css"


def test_normalize_rejects_nul_and_placeholders() -> None:
    assert normalize_repo_path("index.html", "a\x00b.css") is None
    assert normalize_repo_path("index.html", "{{ asset }}.css") is None
    assert normalize_repo_path("index.html", "${asset}.css") is None
    assert normalize_repo_path("index.html", "%(asset)s.css") is None
    assert normalize_repo_path("index.html", "<% asset %>.css") is None


def test_normalize_rejects_external_urls() -> None:
    assert normalize_repo_path("index.html", "https://cdn.example/app.css") is None
    assert normalize_repo_path("index.html", "//cdn.example/app.css") is None
    assert normalize_repo_path("index.html", "data:text/css,body{}") is None


def test_normalize_handles_windows_separators() -> None:
    assert normalize_repo_path("src\\pages\\index.html", "..\\styles\\app.css") == (
        "src/styles/app.css"
    )


def test_classify_external_references() -> None:
    for target in (
        "https://cdn.example/app.css",
        "http://example.com/a.js",
        "//cdn.example/a.js",
        "data:image/png;base64,abc",
        "mailto:user@example.com",
        "tel:+5511999999999",
        "javascript:void(0)",
        "blob:https://example.com/id",
    ):
        assert (
            classify_reference(
                target,
                known_paths=frozenset(),
                tree_complete=True,
            )
            == "external"
        )


def test_classify_fragment_is_resolved() -> None:
    assert (
        classify_reference(
            "#section",
            known_paths=frozenset(),
            tree_complete=True,
        )
        == "resolved"
    )


def test_classify_known_absolute_and_relative_paths() -> None:
    known = frozenset({"assets/app.css", "src/main.js"})
    assert (
        classify_reference("/assets/app.css", known_paths=known, tree_complete=True)
        == "resolved"
    )
    assert (
        classify_reference("src/main.js", known_paths=known, tree_complete=True)
        == "resolved"
    )


def test_classify_missing_only_with_complete_tree() -> None:
    known = frozenset({"index.html"})
    assert (
        classify_reference("missing.css", known_paths=known, tree_complete=True)
        == "missing"
    )
    assert (
        classify_reference("missing.css", known_paths=known, tree_complete=False)
        == "unknown"
    )


@pytest.mark.parametrize(
    "target",
    [
        "{{ base }}/style.css",
        "${img}/a.png",
        "%(asset)s.css",
        "<% asset %>.css",
        "a\x00b.css",
        "C:\\site\\style.css",
        "C:/site/style.css",
        "C:",
    ],
)
def test_classify_placeholders_and_drive_paths_are_unknown(target: str) -> None:
    assert (
        classify_reference(
            target,
            known_paths=frozenset({"index.html"}),
            tree_complete=True,
        )
        == "unknown"
    )


def test_classify_placeholder_is_never_missing() -> None:
    assert (
        classify_reference(
            "{{ base }}/style.css",
            known_paths=frozenset(),
            tree_complete=True,
            is_include=True,
        )
        == "unknown"
    )


def test_classify_unresolved_include_is_external() -> None:
    assert (
        classify_reference(
            "totvs.ch",
            known_paths=frozenset({"other.ch"}),
            tree_complete=True,
            is_include=True,
        )
        == "external"
    )
    assert (
        classify_reference(
            "totvs.ch",
            known_paths=frozenset({"totvs.ch"}),
            tree_complete=True,
            is_include=True,
        )
        == "resolved"
    )


def test_iter_html_references() -> None:
    source = (
        '<link rel="stylesheet" href="css/app.css">\n'
        '<script src="js/app.js"></script>\n'
        '<img src="img/logo.png" srcset="img/logo-2x.png 2x, img/logo-3x.png 3x">\n'
    )
    references = list(iter_html_references(source))

    assert [(item.raw, item.kind) for item in references] == [
        ("css/app.css", "stylesheet"),
        ("js/app.js", "script"),
        ("img/logo.png", "image"),
        ("img/logo-2x.png", "image"),
        ("img/logo-3x.png", "image"),
    ]
    assert references[0].line == 1
    assert references[0].column == 1


def test_iter_css_references_ignores_comments() -> None:
    source = (
        '@import url("theme/base.css");\n'
        "/* url(commented/out.png) */\n"
        "body { background: url('img/bg.png'); }\n"
        '@import "theme/print.css";\n'
    )
    references = list(iter_css_references(source))

    assert [(item.raw, item.kind) for item in references] == [
        ("theme/base.css", "import"),
        ("img/bg.png", "asset"),
        ("theme/print.css", "import"),
    ]


def test_iter_css_references_ignores_urls_inside_content_strings() -> None:
    source = (
        'body { content: "url(fake.png)"; }\n'
        'body { content: "@import \'fake.css\'"; }\n'
    )
    assert list(iter_css_references(source)) == []


def test_iter_advpl_includes() -> None:
    source = (
        '#Include "protheus.ch"\n'
        "// #Include \"ignored.ch\"\n"
        "#Include <totvs.ch>\n"
    )
    references = list(iter_advpl_includes(source))

    assert [(item.raw, item.kind) for item in references] == [
        ("protheus.ch", "include"),
        ("totvs.ch", "include"),
    ]
    assert references[0].line == 1
    assert references[1].line == 3
