"""Tests for the SQLAlchemy parameter redaction filter."""

from __future__ import annotations

import io
import logging
import sys

from app.core.logging import (
    REDACTED_PARAMETERS,
    SqlAlchemyParameterRedactionFilter,
    install_sqlalchemy_parameter_redaction,
)


SECRET = "SEGREDO_DO_USUARIO"


def _record(
    *,
    name: str,
    msg: str,
    args: tuple[object, ...] = (),
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_args_are_dropped_and_values_never_reach_the_message() -> None:
    record = _record(
        name="sqlalchemy.engine.Engine",
        msg="INSERT INTO analyses (project_name, source_code) VALUES (?, ?) parameters: %s",
        args=((SECRET,),),
    )

    assert SqlAlchemyParameterRedactionFilter().filter(record) is True

    message = record.getMessage()
    assert SECRET not in message
    assert record.args == ()
    assert message.startswith("INSERT INTO analyses")
    assert REDACTED_PARAMETERS in message


def test_parameters_only_record_keeps_no_template_noise() -> None:
    record = _record(
        name="sqlalchemy.engine.Engine",
        msg="[%s] %r",
        args=("cached", {"source_code": SECRET}),
    )

    SqlAlchemyParameterRedactionFilter().filter(record)

    assert record.getMessage() == REDACTED_PARAMETERS
    assert SECRET not in record.getMessage()


def test_already_interpolated_message_is_redacted() -> None:
    record = _record(
        name="sqlalchemy.engine.Engine",
        msg=f"INSERT INTO analyses (source_code) VALUES (?) "
        f"parameters: {{'source_code': '{SECRET}'}}",
    )

    SqlAlchemyParameterRedactionFilter().filter(record)

    message = str(record.msg)
    assert SECRET not in message
    assert message.startswith("INSERT INTO analyses")
    assert message.endswith(REDACTED_PARAMETERS)


def test_application_records_are_not_affected() -> None:
    record = _record(
        name="app.services.analysis",
        msg="Analysis %s completed with score %s",
        args=("analysis-1", 90),
    )

    assert SqlAlchemyParameterRedactionFilter().filter(record) is True

    assert record.getMessage() == "Analysis analysis-1 completed with score 90"
    assert record.args == ("analysis-1", 90)
    assert not hasattr(record, "parameters_redacted")


def test_traceback_logged_by_the_web_server_is_redacted() -> None:
    try:
        raise RuntimeError(f"boom parameters: {{'source_code': '{SECRET}'}}")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception in ASGI application",
        args=(),
        exc_info=exc_info,
    )

    SqlAlchemyParameterRedactionFilter().filter(record)

    rendered = logging.Formatter().format(record)
    assert SECRET not in rendered
    assert REDACTED_PARAMETERS in rendered


def test_propagated_record_reaches_the_root_handler_redacted() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    logger = logging.getLogger("sqlalchemy.engine.Engine")
    previous_level = root.level
    previous_logger_level = logger.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logger.setLevel(logging.INFO)
    try:
        install_sqlalchemy_parameter_redaction()
        logger.info(
            "INSERT INTO analyses (source_code) VALUES (?) parameters: %s",
            f"{{'source_code': '{SECRET}'}}",
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
        logger.setLevel(previous_logger_level)

    output = stream.getvalue()
    assert SECRET not in output
    assert REDACTED_PARAMETERS in output


def test_filter_is_installed_on_loggers_and_root_handlers() -> None:
    logger = logging.getLogger("sqlalchemy.engine.Engine")
    root = logging.getLogger()
    handler = logging.StreamHandler()
    root.addHandler(handler)
    try:
        install_sqlalchemy_parameter_redaction()
        install_sqlalchemy_parameter_redaction()

        assert any(
            isinstance(item, SqlAlchemyParameterRedactionFilter)
            for item in logger.filters
        )
        assert any(
            isinstance(item, SqlAlchemyParameterRedactionFilter)
            for item in handler.filters
        )
        # Idempotent: a second install must not duplicate filters.
        assert (
            sum(
                isinstance(item, SqlAlchemyParameterRedactionFilter)
                for item in handler.filters
            )
            == 1
        )
    finally:
        root.removeHandler(handler)


def test_cached_exception_text_is_redacted_when_a_handler_formats_it() -> None:
    """Formatting caches ``exc_text``; a later filter must still sanitize it."""
    try:
        raise RuntimeError(f"boom parameters: {{'source_code': '{SECRET}'}}")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception in ASGI application",
        args=(),
        exc_info=exc_info,
    )
    # Simulate a formatter that already rendered the traceback.
    record.exc_text = logging.Formatter().formatException(exc_info)
    assert SECRET in record.exc_text

    SqlAlchemyParameterRedactionFilter().filter(record)

    assert SECRET not in record.exc_text
    assert REDACTED_PARAMETERS in record.exc_text


def test_uvicorn_error_handler_without_propagation_is_redacted() -> None:
    """Real wiring: the filter must land on uvicorn's own handler.

    uvicorn configures ``uvicorn`` with ``propagate = False`` and a private
    ``default`` handler; ``uvicorn.error`` inherits it. Installing only on the
    root handlers would leave this path unprotected.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("uvicorn.error")
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    try:
        install_sqlalchemy_parameter_redaction()
        assert any(
            isinstance(item, SqlAlchemyParameterRedactionFilter) for item in handler.filters
        )

        try:
            raise RuntimeError(f"boom parameters: {{'source_code': '{SECRET}'}}")
        except RuntimeError:
            logger.error("Exception in ASGI application", exc_info=True)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate

    output = stream.getvalue()
    assert "Exception in ASGI application" in output
    assert SECRET not in output
    assert REDACTED_PARAMETERS in output


def test_late_handler_is_covered_after_a_reinstall() -> None:
    """A handler created after the install is uncovered until it runs again."""
    name = "devpilot.tests.late-handler"
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    # Simulate the handler being created after the last install.
    handler.filters.clear()

    def log_statement_error() -> None:
        try:
            raise RuntimeError(f"boom parameters: {{'source_code': '{SECRET}'}}")
        except RuntimeError:
            logger.error("StatementError", exc_info=True)

    try:
        log_statement_error()
        # Documented limitation: handlers registered later are not covered yet.
        assert SECRET in stream.getvalue()

        stream.seek(0)
        stream.truncate(0)
        install_sqlalchemy_parameter_redaction()
        log_statement_error()
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert SECRET not in output
    assert REDACTED_PARAMETERS in output


def test_lifespan_reinstall_covers_handlers_created_after_the_module_install() -> None:
    """Startup re-installs the filter to cover uvicorn handlers created later."""
    from fastapi.testclient import TestClient

    from app.main import app

    name = "devpilot.tests.lifespan-handler"
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    handler.filters.clear()
    def log_statement_error() -> None:
        try:
            raise RuntimeError(f"boom parameters: {{'source_code': '{SECRET}'}}")
        except RuntimeError:
            logger.error("StatementError", exc_info=True)

    try:
        with TestClient(app):
            log_statement_error()
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert SECRET not in output
    assert REDACTED_PARAMETERS in output
