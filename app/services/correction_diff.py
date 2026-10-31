"""Unified diff and download-name helpers for corrections.

Both helpers are pure: no file is written and no path is trusted. Export names
are reduced to a single safe file name so a repository path can never escape
the download directory or break the ``Content-Disposition`` header.
"""

from __future__ import annotations

import difflib
import re

from app.languages.spec import SPECS

#: Language -> extension used for the corrected-file download, derived from
#: :data:`app.languages.spec.SPECS` so the two maps cannot drift apart.
LANGUAGE_EXTENSIONS: dict[str, str] = {
    language: spec.download_suffix() for language, spec in SPECS.items()
}

DEFAULT_EXTENSION = "txt"

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_BASENAME = 120


def build_unified_diff(
    original: str,
    corrected: str,
    path: str | None = None,
) -> str:
    """Return a unified diff between ``original`` and ``corrected``.

    ``path`` only labels the diff headers (``a/<path>`` and ``b/<path>``); it is
    not read from or written to the filesystem.
    """
    label = path.strip() if isinstance(path, str) and path.strip() else "source"
    fromfile = f"a/{label}"
    tofile = f"b/{label}"
    return "".join(
        difflib.unified_diff(
            _diff_lines(original),
            _diff_lines(corrected),
            fromfile=fromfile,
            tofile=tofile,
            n=3,
        )
    )


def iter_added_lines(diff: str) -> list[str]:
    """Return the lines added by ``diff``, without the ``+++`` header.

    The result is empty for an empty diff, so a correction that changes nothing
    cannot smuggle text into the safety checks through the diff.
    """
    added: list[str] = []
    for line in (diff or "").splitlines():
        if not line.startswith("+"):
            continue
        if line.startswith("+++"):
            continue
        added.append(line[1:])
    return added


def export_filename(
    path: str | None,
    language: str | None,
    suffix: str | None = None,
) -> str:
    """Return a sanitized attachment file name.

    Directory components, control characters, and NUL bytes are removed. When
    ``suffix`` is omitted the extension for ``language`` is used (``txt`` for an
    unknown language).
    """
    base = _safe_basename(path)
    extension = (
        suffix.strip().lstrip(".")
        if isinstance(suffix, str) and suffix.strip()
        else LANGUAGE_EXTENSIONS.get((language or "").strip().lower(), DEFAULT_EXTENSION)
    )
    extension = _UNSAFE_NAME_CHARS.sub("", extension) or DEFAULT_EXTENSION
    return f"{base}.{extension}"


def _diff_lines(value: str) -> list[str]:
    """Split into lines, guaranteeing a trailing newline for a clean diff."""
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    lines = value.splitlines(keepends=True)
    return [line if line.endswith("\n") else line + "\n" for line in lines]


def _safe_basename(path: str | None) -> str:
    raw = path if isinstance(path, str) else ""
    raw = _CONTROL_CHARS.sub("", raw)
    name = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if "." in name:
        name = name.rsplit(".", 1)[0]
    name = _UNSAFE_NAME_CHARS.sub("_", name).strip("._")
    name = name[:_MAX_BASENAME]
    return name or "correction"
