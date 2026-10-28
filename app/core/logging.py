"""Logging safety helpers.

SQLAlchemy logs SQL statements and, when ``echo`` is enabled (or when an
exception is rendered), the bound parameters.  Those parameters can contain
analyzed user code, so the application never relies on the logger
configuration alone: a filter removes them before any handler receives the
record.

The filter keeps the SQL template (useful for diagnosing schema problems) and
replaces the parameter payload with the ``[parameters redacted]`` marker.  It is
installed on the ``sqlalchemy*`` loggers, on every handler already registered
for any logger (for example the ``default`` handler uvicorn attaches to
``uvicorn``/``uvicorn.error`` with ``propagate = False``), and on the root
handlers.  That wiring matters: an unhandled ``StatementError`` is rendered by
the web server, not by SQLAlchemy, and a handler without the filter would log
the bound parameters verbatim even when the root handlers are protected.

Loggers/handlers created after the install (for example uvicorn reconfiguring
logging during startup) are not covered until the function runs again, which is
why both the module import and the application lifespan re-install it.
"""

from __future__ import annotations

import logging
import re
from typing import Final

REDACTED_PARAMETERS: Final[str] = "[parameters redacted]"

# ``parameters:`` is how SQLAlchemy renders bound parameters in the message
# (``... parameters: (1, 'source')`` or ``... parameters: {...}``) and in
# exception text.  Everything after the marker is user data.
_PARAMETERS_RE: Final[re.Pattern[str]] = re.compile(
    r"(parameters:).*$",
    re.IGNORECASE | re.DOTALL,
)

_SQL_STATEMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*\[?"
    r"(?:SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|ALTER|DROP|PRAGMA|BEGIN|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)


class SqlAlchemyParameterRedactionFilter(logging.Filter):
    """Remove bound SQL parameters from SQLAlchemy log records.

    The record is never rejected: only its parameter payload is replaced, so
    operational logs keep the statement and the surrounding diagnostics.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # SQLAlchemy's own loggers are always sanitized. For any other logger,
        # only the rendered traceback is inspected: an unhandled StatementError
        # is often logged by the web server (``uvicorn.error``), not by
        # SQLAlchemy, and it would otherwise carry the same parameters.
        if not record.name.startswith("sqlalchemy"):
            self._redact_exception(record)
            return True

        message = str(record.msg)
        if record.args:
            # The formatter would interpolate the values into the message, so
            # they must be dropped before that happens.
            record.args = ()
            if _PARAMETERS_RE.search(message):
                message = _PARAMETERS_RE.sub(
                    rf"\1 {REDACTED_PARAMETERS}", message
                )
            elif _SQL_STATEMENT_RE.match(message):
                # Keep the SQL template, annotate that the values were removed.
                message = f"{message} {REDACTED_PARAMETERS}"
            else:
                # A parameters-only record (for example ``"[%s] %r"``): the
                # template has no diagnostic value without its values.
                message = REDACTED_PARAMETERS
            record.msg = message
            setattr(record, "parameters_redacted", True)
        elif _PARAMETERS_RE.search(message):
            # Message already interpolated (older SQLAlchemy formats, or a
            # log record created with a fully formatted string).
            record.msg = _PARAMETERS_RE.sub(
                rf"\1 {REDACTED_PARAMETERS}", message
            )
            setattr(record, "parameters_redacted", True)

        self._redact_exception(record)
        return True

    @staticmethod
    def _redact_exception(record: logging.LogRecord) -> None:
        """Sanitize a traceback that already contains bound parameters.

        ``logging.Formatter.format`` caches the rendered traceback on
        ``record.exc_text``; a second filter (or a handler reached after the
        logger filter) must sanitize that cached text too, otherwise the raw
        parameters would still be written.
        """
        if record.exc_text:
            if _PARAMETERS_RE.search(record.exc_text):
                record.exc_text = _PARAMETERS_RE.sub(
                    rf"\1 {REDACTED_PARAMETERS}", record.exc_text
                )
            return
        if not record.exc_info:
            return
        rendered = logging.Formatter().formatException(record.exc_info)
        if _PARAMETERS_RE.search(rendered):
            record.exc_text = _PARAMETERS_RE.sub(
                rf"\1 {REDACTED_PARAMETERS}", rendered
            )


def _has_redaction_filter(target: logging.Logger | logging.Handler) -> bool:
    return any(
        isinstance(item, SqlAlchemyParameterRedactionFilter)
        for item in target.filters
    )


def _sqlalchemy_loggers() -> list[logging.Logger]:
    """Return the existing ``sqlalchemy*`` loggers, including the parent."""
    names = {
        name
        for name in logging.root.manager.loggerDict
        if name == "sqlalchemy" or name.startswith("sqlalchemy.")
    }
    names.add("sqlalchemy")
    return [logging.getLogger(name) for name in sorted(names)]


def _registered_loggers() -> list[logging.Logger]:
    """Return every logger already registered, including the root logger.

    ``loggerDict`` also stores placeholders for parents that were referenced but
    never instantiated; only real ``Logger`` instances expose ``handlers``.
    """
    loggers: list[logging.Logger] = [logging.getLogger()]
    for value in logging.root.manager.loggerDict.values():
        if isinstance(value, logging.Logger) and value not in loggers:
            loggers.append(value)
    return loggers


def _add_filter(
    target: logging.Logger | logging.Handler,
    redaction: SqlAlchemyParameterRedactionFilter,
) -> None:
    if not _has_redaction_filter(target):
        target.addFilter(redaction)


def install_sqlalchemy_parameter_redaction() -> SqlAlchemyParameterRedactionFilter:
    """Install the redaction filter and return it (idempotent).

    It is attached to every existing ``sqlalchemy*`` logger (so a logger with
    its own handler is covered), to every handler of every registered logger
    (so handlers that are not the root handler -- notably uvicorn's ``default``
    handler, which receives ``uvicorn.error`` records with ``propagate =
    False`` -- are covered), and to the root handlers.  Loggers created later
    are covered on the next call; the application re-installs the filter at
    import time and on every lifespan startup.
    """
    redaction = SqlAlchemyParameterRedactionFilter()

    for logger in _sqlalchemy_loggers():
        _add_filter(logger, redaction)

    for logger in _registered_loggers():
        for handler in logger.handlers:
            _add_filter(handler, redaction)

    for handler in logging.getLogger().handlers:
        _add_filter(handler, redaction)

    return redaction


def install_sqlalchemy_logging() -> SqlAlchemyParameterRedactionFilter:
    """Compatibility alias used by the application startup."""
    return install_sqlalchemy_parameter_redaction()


__all__ = [
    "REDACTED_PARAMETERS",
    "SqlAlchemyParameterRedactionFilter",
    "install_sqlalchemy_logging",
    "install_sqlalchemy_parameter_redaction",
]
