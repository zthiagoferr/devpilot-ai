"""Safe normalization of repository-relative paths.

Repository paths arrive from clients (analysis context, correction requests) and
are only ever reference metadata: they are normalized to POSIX form and rejected
when they could escape the repository root. The helper lives in ``core`` so the
request schemas can validate a path without importing an application service.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

#: A leading drive letter (``C:``) means the value is not repository-relative.
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class InvalidRepositoryPathError(ValueError):
    """Raised when a repository path is unsafe or malformed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def normalize_repository_path(path: Any) -> str:
    """Return a safe repository-relative POSIX path or raise.

    Absolute paths (POSIX, Windows drive, or UNC), NUL bytes, empty values, and
    anything that normalizes outside the repository root are rejected. Input
    backslashes are treated as separators, so a Windows client sends the same
    logical path as a POSIX one.
    """
    if not isinstance(path, str):
        raise InvalidRepositoryPathError(
            "Repository context paths must be strings."
        )
    value = path.strip().replace("\\", "/")
    if not value or "\x00" in value:
        raise InvalidRepositoryPathError(
            "Repository context paths must be non-empty and free of NUL bytes."
        )
    if value.startswith("/") or _WINDOWS_DRIVE_RE.match(value):
        raise InvalidRepositoryPathError(
            f"Repository context path must be relative: {path!r}."
        )
    normalized = posixpath.normpath(value)
    if (
        normalized in ("", ".")
        or normalized == ".."
        or normalized.startswith("../")
    ):
        raise InvalidRepositoryPathError(
            f"Repository context path escapes the repository root: {path!r}."
        )
    return normalized
