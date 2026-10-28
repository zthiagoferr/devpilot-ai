"""Deterministic repository relation graph.

The graph is built only from the reference scanners in
:mod:`app.languages.references`; it never reads the filesystem, never executes
the analyzed source, and never calls an LLM. Relations are metadata: they never
change an analysis score or its issues.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Callable

from app.languages.detector import language_for_extension
from app.languages.references import (
    Reference,
    classify_reference,
    iter_advpl_includes,
    iter_css_references,
    iter_html_references,
    normalize_repo_path,
)

RELATIONS_VERSION = 1
RELATIONS_GENERATOR = "deterministic"

_REFERENCE_EXTRACTORS: dict[str, Callable[[str], Iterator[Reference]]] = {
    "html": iter_html_references,
    "css": iter_css_references,
    "advpl": iter_advpl_includes,
}

_STATUSES: tuple[str, ...] = ("resolved", "missing", "external", "unknown")


@dataclass(frozen=True, slots=True)
class RepositorySource:
    """One repository file available to the relation builder."""

    path: str
    source_code: str
    language: str


def _clean_path(path: Any) -> str:
    return str(path).replace("\\", "/").lstrip("/")


def _summary(statuses: Iterable[str]) -> dict[str, int]:
    counts = {status: 0 for status in _STATUSES}
    for status in statuses:
        if status in counts:
            counts[status] += 1
    return counts


def _apps_json_metadata(
    apps_json: dict[str, Any] | str | None,
    apps_json_path: str | None,
) -> dict[str, Any]:
    """Return the Protheus ``apps.json`` metadata without ever guessing."""
    payload: Any = apps_json
    parsed = False
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
            parsed = True
        except (ValueError, TypeError):
            payload = None
    elif isinstance(payload, dict):
        parsed = True

    applications = 0
    keys: list[str] = []
    if isinstance(payload, dict):
        keys = sorted(str(key) for key in payload.keys())
        applications_value = payload.get("applications")
        if isinstance(applications_value, (dict, list)):
            applications = len(applications_value)

    return {
        "path": apps_json_path,
        "present": apps_json is not None,
        "parsed": parsed,
        "applications": applications,
        "keys": keys,
    }


def _error_result(
    apps_json: dict[str, Any] | str | None,
    apps_json_path: str | None,
) -> dict[str, Any]:
    return {
        "version": RELATIONS_VERSION,
        "generated_by": RELATIONS_GENERATOR,
        "truncated": True,
        "tree_complete": False,
        "summary": _summary(()),
        "edges": [],
        "nodes": [],
        "protheus": {
            "apps_json": _apps_json_metadata(apps_json, apps_json_path),
        },
        "error": "relations_unavailable",
    }


def build_repository_relations(
    sources: Iterable[RepositorySource],
    *,
    known_paths: frozenset[str] | set[str] | None = None,
    tree_complete: bool = True,
    truncated: bool = False,
    apps_json: dict[str, Any] | str | None = None,
    apps_json_path: str | None = None,
    max_edges: int = 5000,
) -> dict[str, Any]:
    """Return the deterministic relation graph of ``sources``.

    ``known_paths`` is the repository tree. When it is ``None`` the tree is
    assumed incomplete for safety, so unresolved references are reported as
    ``unknown`` rather than ``missing``. Any internal failure is contained in a
    controlled ``relations_unavailable`` result: relations must never break an
    analysis.
    """
    try:
        return _build(
            sources,
            known_paths=known_paths,
            tree_complete=tree_complete,
            truncated=truncated,
            apps_json=apps_json,
            apps_json_path=apps_json_path,
            max_edges=max_edges,
        )
    except Exception:  # noqa: BLE001 - relations are best-effort metadata
        return _error_result(apps_json, apps_json_path)


def _build(
    sources: Iterable[RepositorySource],
    *,
    known_paths: frozenset[str] | set[str] | None,
    tree_complete: bool,
    truncated: bool,
    apps_json: dict[str, Any] | str | None,
    apps_json_path: str | None,
    max_edges: int,
) -> dict[str, Any]:
    known = (
        frozenset(_clean_path(path) for path in known_paths)
        if known_paths is not None
        else frozenset()
    )
    effective_complete = bool(tree_complete) and known_paths is not None
    edge_limit = max(0, int(max_edges))

    source_by_path: dict[str, RepositorySource] = {}
    for source in sources:
        path = _clean_path(source.path)
        if path and path not in source_by_path:
            source_by_path[path] = source

    edges: list[dict[str, Any]] = []
    referenced: dict[str, bool] = {}
    graph_truncated = bool(truncated)

    for path, source in source_by_path.items():
        extractor = _REFERENCE_EXTRACTORS.get(
            str(source.language or "").strip().lower()
        )
        if extractor is None:
            continue
        for reference in extractor(source.source_code):
            normalized = normalize_repo_path(path, reference.raw)
            target = normalized if normalized is not None else reference.raw
            is_include = reference.kind == "include"
            status = classify_reference(
                target,
                known_paths=known,
                tree_complete=effective_complete,
                is_include=is_include,
            )
            if len(edges) >= edge_limit:
                graph_truncated = True
                break

            edges.append(
                {
                    "source": path,
                    "target": target,
                    "kind": reference.kind,
                    "raw": reference.raw,
                    "status": status,
                    "line": reference.line,
                    "column": reference.column,
                }
            )
            if status == "resolved" and normalized is not None and normalized not in source_by_path:
                referenced[normalized] = True
        else:
            continue
        # The edge limit was reached inside this source; stop scanning.
        break

    nodes: list[dict[str, Any]] = [
        {
            "path": path,
            "language": str(source.language or "unknown"),
            "present": True,
        }
        for path, source in source_by_path.items()
    ]
    for path in referenced:
        if path not in source_by_path:
            nodes.append(
                {
                    "path": path,
                    "language": language_for_extension(path) or "unknown",
                    "present": False,
                }
            )
    nodes.sort(key=lambda node: str(node["path"]))

    return {
        "version": RELATIONS_VERSION,
        "generated_by": RELATIONS_GENERATOR,
        "truncated": graph_truncated,
        "tree_complete": effective_complete,
        "summary": _summary(edge["status"] for edge in edges),
        "edges": edges,
        "nodes": nodes,
        "protheus": {
            "apps_json": _apps_json_metadata(apps_json, apps_json_path),
        },
    }


__all__ = ["RepositorySource", "build_repository_relations"]
