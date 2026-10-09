"""Public persistence-layer interfaces.

The package keeps its imports lazy: importing :mod:`app.db` does not import
application/API modules or initialize a database engine, session, connection,
or schema.  The underlying persistence modules are loaded only when one of
their public interfaces is requested.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

# Object name -> module loaded on first access.  Names are kept explicit so
# ``from app.db import <name>`` works without a wildcard import.
_DATABASE_EXPORTS = frozenset(
    {
        "DATABASE_URL",
        "close_engine",
        "dispose_engine",
        "get_db",
        "get_db_session",
        "get_engine",
        "get_session",
        "get_session_factory",
        "session_context",
        "session_scope",
    }
)

_MODEL_EXPORTS = frozenset(
    {
        "Analysis",
        "Base",
    }
)

__all__ = tuple(sorted((*_DATABASE_EXPORTS, *_MODEL_EXPORTS)))


def __getattr__(name: str) -> Any:
    """Resolve persistence interfaces without eager package imports."""
    if name in _DATABASE_EXPORTS:
        module = import_module(".session", __name__)
        try:
            return getattr(module, name)
        except AttributeError as exc:
            raise AttributeError(
                f"module {__name__!r} has no database interface {name!r}"
            ) from exc

    if name in _MODEL_EXPORTS:
        module = import_module(".models", __name__)
        try:
            return getattr(module, name)
        except AttributeError as exc:
            raise AttributeError(
                f"module {__name__!r} has no model interface {name!r}"
            ) from exc

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
