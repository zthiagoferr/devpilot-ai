"""FastAPI API package.

Importing :mod:`app.api` intentionally does not import the individual routers
eagerly.  The dependency helpers that wire the analysis runtime are re-exported
from :mod:`app.api.analysis` on first access so existing imports keep working
without creating engines, sessions, or tables.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "get_analysis_repository",
    "get_analysis_service",
]

_DEPENDENCY_EXPORTS = frozenset(__all__)


def __getattr__(name: str) -> Any:
    """Resolve API dependency helpers lazily from :mod:`app.api.analysis`."""
    if name in _DEPENDENCY_EXPORTS:
        module = import_module(".analysis", __name__)
        try:
            return getattr(module, name)
        except AttributeError as exc:
            raise AttributeError(
                f"module {__name__!r} has no interface {name!r}"
            ) from exc

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
