"""Public persistence-layer interfaces.

The package deliberately keeps its imports lazy.  Importing :mod:`app.db`
therefore does not import application/API modules or initialise a database
engine, session, connection, or schema.  The underlying persistence modules
are loaded only when one of their public interfaces is requested.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_DATABASE_EXPORTS = frozenset(
    {
        "Base",
        "DATABASE_URL",
        "SessionLocal",
        "engine",
        "get_db",
        "get_session",
        "session_factory",
    }
)

# Keep the package facade explicit for normal wildcard imports while allowing
# additional model classes to be resolved lazily from app.db.models.
_MODEL_EXPORTS = (
    "Agent",
    "Analysis",
    "AnalysisResult",
    "CodeAnalysis",
    "Conversation",
    "DocumentationAnalysis",
    "Message",
    "Project",
    "Report",
    "Task",
    "TestAnalysis",
    "User",
)

__all__ = tuple(sorted((*_DATABASE_EXPORTS, *_MODEL_EXPORTS)))


def __getattr__(name: str) -> Any:
    """Resolve persistence interfaces without eager package imports."""
    if name in _DATABASE_EXPORTS:
        module = import_module(".database", __name__)
        try:
            return getattr(module, name)
        except AttributeError as exc:
            raise AttributeError(
                f"module {__name__!r} has no database interface {name!r}"
            ) from exc

    if name in _MODEL_EXPORTS or (name and name[0].isupper()):
        try:
            module = import_module(".models", __name__)
        except ModuleNotFoundError as exc:
            if exc.name == f"{__name__}.models":
                raise AttributeError(
                    f"module {__name__!r} has no model interface {name!r}"
                ) from exc
            raise

        try:
            value = getattr(module, name)
        except AttributeError as exc:
            raise AttributeError(
                f"module {__name__!r} has no model interface {name!r}"
            ) from exc

        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
