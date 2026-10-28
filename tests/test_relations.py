"""Unit tests for the deterministic repository relation graph."""

from __future__ import annotations

from collections.abc import Iterator

from app.languages.references import Reference
from app.services import relations as relations_module
from app.services.relations import RepositorySource, build_repository_relations

HTML_SOURCE = (
    '<link rel="stylesheet" href="css/app.css">\n'
    '<script src="js/app.js"></script>\n'
    '<img src="https://cdn.example/logo.png">\n'
)


def _source(path: str = "index.html", source: str = HTML_SOURCE, language: str = "html"):
    return RepositorySource(path=path, source_code=source, language=language)


def test_edges_are_limited_and_flag_the_result_as_truncated() -> None:
    result = build_repository_relations(
        [_source()],
        known_paths=frozenset({"index.html", "css/app.css", "js/app.js"}),
        tree_complete=True,
        max_edges=1,
    )

    assert len(result["edges"]) == 1
    assert result["truncated"] is True
    assert result["summary"]["resolved"] == 1
    assert result["summary"]["external"] == 0


def test_missing_known_paths_means_unknown_not_missing() -> None:
    result = build_repository_relations(
        [_source()],
        known_paths=None,
        tree_complete=True,
    )

    statuses = {edge["target"]: edge["status"] for edge in result["edges"]}
    assert statuses["css/app.css"] == "unknown"
    assert statuses["js/app.js"] == "unknown"
    assert statuses["https://cdn.example/logo.png"] == "external"
    assert result["tree_complete"] is False
    assert result["summary"]["missing"] == 0


def test_css_references_inside_strings_and_comments_are_ignored() -> None:
    css = (
        "/* url(commented.png) */\n"
        'body { content: "url(fake.png)"; }\n'
        "body { background: url(real.png); }\n"
    )

    result = build_repository_relations(
        [_source("css/app.css", css, "css")],
        known_paths=frozenset({"css/app.css", "css/real.png"}),
        tree_complete=True,
    )

    assert [(edge["target"], edge["status"]) for edge in result["edges"]] == [
        ("css/real.png", "resolved")
    ]


def test_apps_json_string_is_parsed_as_metadata() -> None:
    result = build_repository_relations(
        [],
        known_paths=frozenset({"apps.json"}),
        apps_json='{"applications": {"job": {}, "report": {}}}',
        apps_json_path="apps.json",
    )

    apps_json = result["protheus"]["apps_json"]
    assert apps_json["present"] is True
    assert apps_json["parsed"] is True
    assert apps_json["applications"] == 2
    assert apps_json["keys"] == ["applications"]


def test_internal_failure_returns_a_controlled_result(monkeypatch) -> None:
    def explode(source: str) -> Iterator[Reference]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setitem(
        relations_module._REFERENCE_EXTRACTORS,
        "html",
        explode,
    )

    result = build_repository_relations(
        [_source()],
        known_paths=frozenset({"index.html"}),
    )

    assert result["error"] == "relations_unavailable"
    assert result["edges"] == []
    assert result["truncated"] is True
    assert result["version"] == 1
