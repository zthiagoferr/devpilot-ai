"""FastAPI dependency helpers for the analysis runtime.

The dependencies in this module only assemble repository and service objects
around the session supplied by the application's existing database dependency.
They do not create engines, sessions, tables, or database connections.
"""

from typing import Any, Callable

from fastapi import Depends


try:
    from app.db.session import get_async_session
except ImportError:
    try:
        from app.db.session import get_db as get_async_session
    except ImportError:
        try:
            from app.database import get_async_session
        except ImportError:
            try:
                from app.database import get_db as get_async_session
            except ImportError:
                async def get_async_session() -> Any:
                    """Fail clearly when no application session provider exists."""

                    raise RuntimeError(
                        "No async database session dependency is configured."
                    )


# Keep the dependency signatures explicit while allowing the existing session
# provider to remain the sole owner of session creation and cleanup.
SessionDependency = Callable[..., Any]


def _load_analysis_repository() -> type[Any]:
    """Load the repository implementation only when the dependency is used."""

    try:
        from app.repositories.analysis_repository import AnalysisRepository
    except ImportError:
        from app.repositories.analysis import AnalysisRepository

    return AnalysisRepository


def _load_analysis_service() -> type[Any]:
    """Load the service implementation only when the dependency is used."""

    try:
        from app.services.analysis_service import AnalysisService
    except ImportError:
        from app.services.analysis import AnalysisService

    return AnalysisService


def get_analysis_repository(
    db: Any = Depends(get_async_session),
) -> Any:
    """Build an analysis repository for the request-scoped database session."""

    repository_class = _load_analysis_repository()
    return repository_class(db)


def get_analysis_service(
    repository: Any = Depends(get_analysis_repository),
) -> Any:
    """Build an analysis service backed by the request-scoped repository."""

    service_class = _load_analysis_service()
    return service_class(repository)


__all__ = [
    "get_analysis_repository",
    "get_analysis_service",
]
