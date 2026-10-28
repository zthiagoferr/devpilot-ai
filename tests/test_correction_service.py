"""Service-level tests for AI corrections against a real SQLite database."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.db.models import Base
from app.db.repositories import AnalysisRepository, CorrectionRepository
from app.llm.fake import FakeLLMProvider
from app.schemas.correction import CorrectionCreate, CorrectionIssueRef
from app.services.correction_errors import (
    CorrectionInvalidResponseError,
    CorrectionNotFoundError,
    CorrectionProviderError,
    CorrectionSafetyError,
    CorrectionSourceTooLargeError,
    CorrectionStateError,
    CorrectionUnavailableError,
)
from app.services.correction_service import CorrectionService
from app.services.llm_service import LLMService


BROKEN_PYTHON = "def compute_total(items)\n    return sum(items)\n"
FIXED_PYTHON = "def compute_total(items):\n    return sum(items)\n"
VALID_PYTHON = "value = 1\n"
NEWLY_BROKEN_PYTHON = "def broken(\n"

ADVPL_SOURCE = "User Function Teste()\nReturn Nil\n"
ADVPL_WITH_NEW_API = (
    "User Function Teste()\n"
    "    FWNovoRecurso()\n"
    "Return Nil\n"
)
ADVPL_WITH_SUCCESS_MESSAGE = (
    "User Function Teste()\n"
    '    MsgInfo("Processo executado com sucesso")\n'
    "Return Nil\n"
)
ADVPL_WITH_ADDED_COMMENT = (
    "User Function Teste()\n"
    '    MsgInfo("Processo executado com sucesso")\n'
    "    // Ajuste aplicado\n"
    "Return Nil\n"
)


def _payload(corrected: str, explanation: str = "Adjusted the reported issue.") -> str:
    return json.dumps(
        {"corrected_code": corrected, "explanation": explanation},
    )


@pytest_asyncio.fixture()
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'corrections.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db_session:
            yield db_session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def analysis(session):
    repository = AnalysisRepository(session)
    record = await repository.create_analysis(
        task="code_analysis",
        project_name="correction-project",
        source_code=BROKEN_PYTHON,
        result={"score": 0, "summary": "", "issues": [], "report": {}},
        user_id="user-1",
    )
    await session.commit()
    return record


def _settings(**overrides):
    values = {
        "correction_max_source_bytes": 200_000,
        "correction_max_corrected_bytes": 1_000_000,
        "llm_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _service(
    session,
    *,
    response: str = "",
    llm_none: bool = False,
    settings=None,
    provider_name: str | None = "fake",
    provider: FakeLLMProvider | None = None,
) -> CorrectionService:
    provider = provider or FakeLLMProvider(response=response)
    llm = None if llm_none else LLMService(provider)
    return CorrectionService(
        CorrectionRepository(session),
        AnalysisRepository(session),
        llm,
        settings=settings or _settings(),
        provider_name=provider_name,
    )


def _request(
    *,
    source_code: str = BROKEN_PYTHON,
    language: str | None = "python",
    file: str | None = "src/calc.py",
    issue: CorrectionIssueRef | None = None,
    analysis_id=None,
    protheus_version: str | None = None,
) -> CorrectionCreate:
    return CorrectionCreate(
        analysis_id=analysis_id,
        file=file,
        language=language,
        source_code=source_code,
        issue=issue
        or CorrectionIssueRef(
            message="Python syntax error: expected ':'",
            severity="critical",
            line=1,
            code="python_syntax",
        ),
        protheus_version=protheus_version,
    )


@pytest.mark.asyncio
async def test_successful_correction_is_persisted_as_pending(
    session,
    analysis,
) -> None:
    service = _service(session, response=_payload(FIXED_PYTHON))

    correction = await service.create(
        _request(analysis_id=analysis.id),
        user_id="user-1",
    )

    assert correction.status == "pending"
    assert correction.origin == "ai"
    assert correction.user_id == "user-1"
    assert correction.analysis_id == analysis.id
    assert correction.language == "python"
    assert correction.file == "src/calc.py"
    assert correction.issue_ref == "python-syntax"
    assert correction.model == "fake"
    assert correction.original_code == BROKEN_PYTHON
    assert correction.corrected_code == FIXED_PYTHON
    assert correction.explanation == "Adjusted the reported issue."
    assert correction.diff.startswith("--- a/src/calc.py")
    assert "\n+++ b/src/calc.py" in correction.diff
    assert correction.created_at is not None
    assert correction.decided_at is None

    validation = correction.post_validation
    assert validation["status"] == "passed"
    assert validation["target_resolved"] is True
    assert validation["issues"] == []
    assert "not an official" in validation["summary"]


@pytest.mark.asyncio
async def test_correction_that_introduces_an_error_fails_validation(
    session,
) -> None:
    service = _service(session, response=_payload(NEWLY_BROKEN_PYTHON))

    correction = await service.create(
        _request(
            source_code=VALID_PYTHON,
            issue=CorrectionIssueRef(message="Unused variable 'value'", line=1),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is True
    assert any(issue["severity"] == "critical" for issue in validation["issues"])
    assert "new high-severity" in validation["summary"]


@pytest.mark.asyncio
async def test_unresolved_target_issue_fails_validation(session) -> None:
    service = _service(session, response=_payload(BROKEN_PYTHON))

    correction = await service.create(_request(), user_id="user-1")

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is False
    assert "still reported" in validation["summary"]


@pytest.mark.asyncio
async def test_new_totvs_identifier_without_version_fails_validation(
    session,
) -> None:
    service = _service(session, response=_payload(ADVPL_WITH_NEW_API))

    correction = await service.create(
        _request(
            source_code=ADVPL_SOURCE,
            language="advpl",
            file="src/teste.prw",
            issue=CorrectionIssueRef(
                message="Missing initialization",
                severity="medium",
                code="advpl_init",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert correction.language == "advpl"
    assert validation["status"] == "failed"
    assert any(
        issue.get("cause") == "unverified_totvs_api"
        for issue in validation["issues"]
    )
    assert "TOTVS" in validation["summary"]


@pytest.mark.asyncio
async def test_correction_requires_a_configured_provider(session) -> None:
    service = _service(session, llm_none=True)

    with pytest.raises(CorrectionUnavailableError):
        await service.create(_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_invalid_provider_json_raises_invalid_response(session) -> None:
    service = _service(session, response="not a json payload")

    with pytest.raises(CorrectionInvalidResponseError):
        await service.create(_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_oversized_source_is_rejected(session) -> None:
    service = _service(
        session,
        response=_payload(FIXED_PYTHON),
        settings=_settings(correction_max_source_bytes=10),
    )

    with pytest.raises(CorrectionSourceTooLargeError) as excinfo:
        await service.create(_request(), user_id="user-1")

    assert excinfo.value.limit == 10


@pytest.mark.asyncio
async def test_oversized_corrected_code_is_rejected(session) -> None:
    service = _service(
        session,
        response=_payload("x = 1\n" * 100),
        settings=_settings(correction_max_corrected_bytes=50),
    )

    with pytest.raises(CorrectionInvalidResponseError):
        await service.create(_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_execution_claim_is_rejected(session) -> None:
    service = _service(
        session,
        response=_payload(
            FIXED_PYTHON,
            explanation="The corrected file compiles successfully.",
        ),
    )

    with pytest.raises(CorrectionSafetyError):
        await service.create(_request(), user_id="user-1")


class _ExplodingProvider(FakeLLMProvider):
    async def generate(self, prompt: str, *, system_prompt: str | None = None):
        raise RuntimeError("boom: provider-key-should-not-leak")


@pytest.mark.asyncio
async def test_provider_errors_are_sanitized(session) -> None:
    service = _service(session, provider=_ExplodingProvider())

    with pytest.raises(CorrectionProviderError) as excinfo:
        await service.create(_request(), user_id="user-1")

    assert "provider-key-should-not-leak" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_decision_is_idempotent_and_stateful(session) -> None:
    service = _service(session, response=_payload(FIXED_PYTHON))
    correction = await service.create(_request(), user_id="user-1")

    approved = await service.decide(correction.id, "approved", user_id="user-1")
    assert approved.status == "approved"
    first_decided_at = approved.decided_at
    assert first_decided_at is not None

    again = await service.decide(correction.id, "approved", user_id="user-1")
    assert again.status == "approved"
    assert again.decided_at == first_decided_at

    with pytest.raises(CorrectionStateError):
        await service.decide(correction.id, "rejected", user_id="user-1")


@pytest.mark.asyncio
async def test_reads_are_owner_scoped(session) -> None:
    service = _service(session, response=_payload(FIXED_PYTHON))
    correction = await service.create(_request(), user_id="user-1")

    with pytest.raises(CorrectionNotFoundError):
        await service.get(correction.id, user_id="user-2")

    with pytest.raises(CorrectionNotFoundError):
        await service.decide(correction.id, "approved", user_id="user-2")

    assert (await service.get(correction.id, user_id="user-1")).id == correction.id


@pytest.mark.asyncio
async def test_anonymous_correction_is_not_readable(session) -> None:
    service = _service(session, response=_payload(FIXED_PYTHON))
    correction = await service.create(_request(), user_id=None)

    with pytest.raises(CorrectionNotFoundError):
        await service.get(correction.id, user_id="user-1")


@pytest.mark.asyncio
async def test_foreign_analysis_is_not_visible(session, analysis) -> None:
    service = _service(session, response=_payload(FIXED_PYTHON))

    with pytest.raises(CorrectionNotFoundError):
        await service.create(
            _request(analysis_id=analysis.id),
            user_id="user-2",
        )

    with pytest.raises(CorrectionNotFoundError):
        await service.create(_request(analysis_id=analysis.id), user_id=None)


@pytest.mark.asyncio
async def test_list_for_analysis_is_owner_scoped(session, analysis) -> None:
    service = _service(session, response=_payload(FIXED_PYTHON))
    first = await service.create(_request(analysis_id=analysis.id), user_id="user-1")
    second = await service.create(_request(analysis_id=analysis.id), user_id="user-1")

    listed = await service.list_for_analysis(analysis.id, user_id="user-1")
    assert {item.id for item in listed} == {first.id, second.id}

    with pytest.raises(CorrectionNotFoundError):
        await service.list_for_analysis(analysis.id, user_id="user-2")


@pytest.mark.asyncio
async def test_export_formats(session, analysis) -> None:
    service = _service(session, response=_payload(FIXED_PYTHON))
    correction = await service.create(
        _request(analysis_id=analysis.id),
        user_id="user-1",
    )

    content_type, filename, body = await service.export(
        correction.id,
        user_id="user-1",
        fmt="corrected",
    )
    assert content_type == "text/plain; charset=utf-8"
    assert filename == "calc.py"
    assert body == FIXED_PYTHON.encode("utf-8")

    content_type, filename, body = await service.export(
        correction.id,
        user_id="user-1",
        fmt="diff",
    )
    assert content_type == "text/x-diff; charset=utf-8"
    assert filename == "calc.diff"
    assert b"--- a/src/calc.py" in body

    content_type, filename, body = await service.export(
        correction.id,
        user_id="user-1",
        fmt="json",
    )
    assert content_type == "application/json"
    assert filename == "calc.json"
    payload = json.loads(body)
    assert payload["id"] == str(correction.id)
    assert payload["corrected_code"] == FIXED_PYTHON


@pytest.mark.asyncio
async def test_export_of_foreign_correction_is_not_found(session) -> None:
    service = _service(session, response=_payload(FIXED_PYTHON))
    correction = await service.create(_request(), user_id="user-1")

    with pytest.raises(CorrectionNotFoundError):
        await service.export(correction.id, user_id="user-2", fmt="corrected")


@pytest.mark.asyncio
async def test_language_is_detected_from_the_file_when_omitted(session) -> None:
    service = _service(session, response=_payload("value = 2\n"))

    correction = await service.create(
        _request(source_code="value = 1\n", language=None, file="module.py"),
        user_id="user-1",
    )

    assert correction.language == "python"


# --------------------------------------------------------------------- ALTO-1
@pytest.mark.asyncio
async def test_preexisting_success_message_in_the_source_is_not_rejected(
    session,
) -> None:
    """The user's own strings must not trip the execution-claim guard.

    ``MsgInfo("Processo executado com sucesso")`` is common in Protheus, and the
    corrected file always contains the original code verbatim.
    """
    service = _service(
        session,
        response=_payload(ADVPL_WITH_ADDED_COMMENT, "Added a clarifying comment."),
    )

    correction = await service.create(
        _request(
            source_code=ADVPL_WITH_SUCCESS_MESSAGE,
            language="advpl",
            file="src/teste.prw",
            issue=CorrectionIssueRef(
                message="Falta um comentário explicando o fluxo",
                severity="low",
                line=2,
            ),
        ),
        user_id="user-1",
    )

    assert correction.corrected_code == ADVPL_WITH_ADDED_COMMENT
    assert correction.post_validation["status"] == "passed"


@pytest.mark.asyncio
async def test_execution_claim_in_the_explanation_is_still_rejected_for_advpl(
    session,
) -> None:
    service = _service(
        session,
        response=_payload(
            ADVPL_WITH_ADDED_COMMENT,
            "The corrected file compiles successfully.",
        ),
    )

    with pytest.raises(CorrectionSafetyError):
        await service.create(
            _request(
                source_code=ADVPL_WITH_SUCCESS_MESSAGE,
                language="advpl",
                file="src/teste.prw",
            ),
            user_id="user-1",
        )


@pytest.mark.asyncio
async def test_execution_claim_in_an_added_line_is_rejected(session) -> None:
    added_claim = ADVPL_SOURCE.replace(
        "Return Nil",
        '    MsgInfo("Processo executado com sucesso")\nReturn Nil',
    )
    service = _service(session, response=_payload(added_claim))

    with pytest.raises(CorrectionSafetyError):
        await service.create(
            _request(
                source_code=ADVPL_SOURCE,
                language="advpl",
                file="src/teste.prw",
            ),
            user_id="user-1",
        )


# --------------------------------------------------------------------- ALTO-2
@pytest.mark.asyncio
async def test_unchanged_correction_is_failed_when_baseline_has_issues(
    session,
) -> None:
    """Identical code cannot fix anything: never report ``passed``."""
    service = _service(session, response=_payload(BROKEN_PYTHON))

    correction = await service.create(
        _request(
            issue=CorrectionIssueRef(
                message="Missing module docstring",
                severity="low",
            )
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert correction.corrected_code == BROKEN_PYTHON
    assert validation["status"] == "failed"
    assert "identical to the original" in validation["summary"]


@pytest.mark.asyncio
async def test_legacy_python_message_matches_the_validator_message(session) -> None:
    """``message=exc.msg`` ("expected ':'") must match the prefixed message."""
    corrected_still_broken = (
        "def compute_total(items)\n    return sum(items) + 1\n"
    )
    service = _service(session, response=_payload(corrected_still_broken))

    correction = await service.create(
        _request(
            issue=CorrectionIssueRef(
                message="expected ':'",
                severity="critical",
                line=1,
            )
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is False
    assert "still reported" in validation["summary"]


@pytest.mark.asyncio
async def test_baseline_high_error_on_the_same_line_matches_the_target(
    session,
) -> None:
    """A rewritten but still broken line is the same problem, not a new one."""
    corrected_reworded = "def compute_total(items)\n    return sum(items) + 1\n"
    service = _service(session, response=_payload(corrected_reworded))

    correction = await service.create(
        _request(
            issue=CorrectionIssueRef(
                message="The parameter list is invalid",
                severity="critical",
                line=1,
            )
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["target_resolved"] is False
    assert validation["status"] == "failed"


# ------------------------------------------------------------- extra coverage
class _SlowProvider(FakeLLMProvider):
    async def generate(self, prompt: str, *, system_prompt: str | None = None):
        await asyncio.sleep(0.2)
        return await super().generate(prompt, system_prompt=system_prompt)


@pytest.mark.asyncio
async def test_slow_provider_times_out_as_a_provider_error(session) -> None:
    service = _service(
        session,
        provider=_SlowProvider(response=_payload(FIXED_PYTHON)),
        settings=_settings(llm_timeout_seconds=0.01),
    )

    with pytest.raises(CorrectionProviderError):
        await service.create(_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_unicode_and_emoji_in_issue_and_explanation(session) -> None:
    emoji_explanation = "Corrigido: variável não definida 🚀 ✅"
    service = _service(
        session,
        response=_payload("valor = 2\n", emoji_explanation),
    )

    correction = await service.create(
        _request(
            source_code="valor = 1\n",
            file="src/módulo.py",
            issue=CorrectionIssueRef(
                message="Variável 'valor' não definida 🚀",
                severity="high",
                line=1,
                rule_id="undef-🚀",
            ),
        ),
        user_id="user-1",
    )

    assert correction.explanation == emoji_explanation
    assert correction.language == "python"
    assert correction.issue_ref
    assert correction.issue_ref.isascii()
    assert correction.diff.startswith("--- a/src/módulo.py")


@pytest.mark.asyncio
async def test_issue_ref_falls_back_for_a_non_ascii_only_message(session) -> None:
    service = _service(session, response=_payload("valor = 2\n"))

    correction = await service.create(
        _request(
            source_code="valor = 1\n",
            issue=CorrectionIssueRef(message="🚀🚀🚀", severity="low"),
        ),
        user_id="user-1",
    )

    assert correction.issue_ref == "issue"
