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
from app.languages.registry import get_validator
from app.llm.base import IncompleteLLMResponseError
from app.llm.fake import FakeLLMProvider
from app.schemas.correction import (
    CorrectionCreate,
    CorrectionIssueRef,
    CorrectionRepositoryContext,
)
from app.services.correction_errors import (
    CorrectionInvalidResponseError,
    CorrectionNoIssuesError,
    CorrectionNotFoundError,
    CorrectionProviderError,
    CorrectionSafetyError,
    CorrectionSourceTooLargeError,
    CorrectionStateError,
    CorrectionTimeoutError,
    CorrectionTooManyIssuesError,
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
    repository_context: CorrectionRepositoryContext | None = None,
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
        repository_context=repository_context,
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
async def test_identical_correction_with_clean_baseline_does_not_claim_a_baseline_problem(
    session,
) -> None:
    """With a clean baseline there is no persisted problem to claim."""
    service = _service(session, response=_payload(VALID_PYTHON))

    correction = await service.create(
        _request(
            source_code=VALID_PYTHON,
            issue=CorrectionIssueRef(
                message="Missing module docstring",
                severity="low",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert correction.corrected_code == VALID_PYTHON
    assert validation["status"] == "failed"
    assert "identical to the original" in validation["summary"]
    assert "no baseline problem" in validation["summary"]
    assert "problem reported in the baseline" not in validation["summary"]


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
async def test_slow_provider_times_out_as_a_timeout_error(session) -> None:
    service = _service(
        session,
        provider=_SlowProvider(response=_payload(FIXED_PYTHON)),
        settings=_settings(llm_timeout_seconds=0.01),
    )

    with pytest.raises(CorrectionTimeoutError):
        await service.create(_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_timeout_log_is_sanitized(session, caplog) -> None:
    marker = "SOURCE_MUST_NOT_APPEAR_IN_LOGS"
    service = _service(
        session,
        provider=_SlowProvider(response=_payload(FIXED_PYTHON)),
        settings=_settings(llm_timeout_seconds=0.01),
    )

    with caplog.at_level("WARNING"):
        with pytest.raises(CorrectionTimeoutError):
            await service.create(
                _request(source_code=VALID_PYTHON + f"# {marker}\n"),
                user_id="user-1",
            )

    assert "correction provider timed out" in caplog.text
    assert "language=python" in caplog.text
    assert marker not in caplog.text
    assert VALID_PYTHON.strip() not in caplog.text


class _IncompleteProvider(FakeLLMProvider):
    async def generate(self, prompt: str, *, system_prompt: str | None = None):
        raise IncompleteLLMResponseError("incomplete")


@pytest.mark.asyncio
async def test_incomplete_provider_response_is_an_invalid_response(session) -> None:
    service = _service(session, provider=_IncompleteProvider())

    with pytest.raises(CorrectionInvalidResponseError) as excinfo:
        await service.create(_request(), user_id="user-1")

    assert "incomplete" in str(excinfo.value).lower()


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


# --------------------------------------------------- Fase C: identidade estável
ADVPL_UNCLOSED_BLOCK = (
    "User Function Teste()\n"
    "    If .T.\n"
    '        MsgInfo("ok")\n'
    "    Return Nil\n"
)

HTML_TWO_IMAGES = """<!DOCTYPE html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doc</title>
</head>
<body>
<img src="a.png">
<img src="b.png">
</body>
</html>
"""

HTML_WITH_UNCLOSED_DIV = """<!DOCTYPE html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doc</title>
</head>
<body>
<div>
<img src="a.png">
</body>
</html>
"""

HTML_VALID = """<!DOCTYPE html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doc</title>
</head>
<body>
<p>Hi</p>
</body>
</html>
"""

HTML_WITH_STYLESHEET = """<!DOCTYPE html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="styles.css">
<title>Doc</title>
</head>
<body>
<p>Hi</p>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_issue_that_only_moves_line_is_not_a_new_issue(session) -> None:
    """An unrelated added line shifts the finding but must not recreate it."""
    corrected = "// header\n" + ADVPL_UNCLOSED_BLOCK
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=ADVPL_UNCLOSED_BLOCK,
            language="advpl",
            file="src/teste.prw",
            issue=CorrectionIssueRef(
                message="Falta um comentário de cabeçalho",
                severity="low",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is True
    assert validation["issues_new"] == []
    assert [issue["cause"] for issue in validation["issues_remaining"]] == [
        "unclosed_block"
    ]
    assert validation["issues_remaining"][0]["line"] == 3
    assert "target resolved but 1 original issue(s) remain" in validation["summary"]
    assert "new high-severity" not in validation["summary"]


@pytest.mark.asyncio
async def test_resolved_target_with_another_original_issue_still_fails(
    session,
) -> None:
    """Fixing the alt text must not hide the still-open <div>."""
    corrected = HTML_WITH_UNCLOSED_DIV.replace(
        '<img src="a.png">',
        '<img src="a.png" alt="Imagem A">',
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=HTML_WITH_UNCLOSED_DIV,
            language="html",
            file="index.html",
            issue=CorrectionIssueRef(
                message="Image is missing an alt attribute.",
                severity="medium",
                line=8,
                cause="missing_alt",
                code="missing_alt",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is True
    assert [issue["cause"] for issue in validation["issues_resolved"]] == [
        "missing_alt"
    ]
    assert [issue["cause"] for issue in validation["issues_remaining"]] == [
        "unclosed_tag"
    ]
    assert validation["issues_new"] == []
    assert "target resolved but 1 original issue(s) remain" in validation["summary"]


@pytest.mark.asyncio
async def test_duplicate_cause_occurrence_left_in_place_is_remaining(session) -> None:
    """Two ``missing_alt`` findings: fixing one leaves the other as remaining."""
    corrected = HTML_TWO_IMAGES.replace(
        '<img src="a.png">',
        '<img src="a.png" alt="Imagem A">',
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=HTML_TWO_IMAGES,
            language="html",
            file="index.html",
            issue=CorrectionIssueRef(
                message="Image is missing an alt attribute.",
                severity="medium",
                line=8,
                cause="missing_alt",
                code="missing_alt",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is True
    assert [issue["cause"] for issue in validation["issues_resolved"]] == [
        "missing_alt"
    ]
    assert [issue["cause"] for issue in validation["issues_remaining"]] == [
        "missing_alt"
    ]
    assert validation["issues_remaining"][0]["line"] == 9
    assert validation["issues_new"] == []
    assert "target resolved but 1 original issue(s) remain" in validation["summary"]


@pytest.mark.asyncio
async def test_legacy_python_target_without_rule_id_matches_a_moved_issue(
    session,
) -> None:
    """A CodeAgent issue (message only) still matches a validator finding."""
    corrected = "# header\n" + BROKEN_PYTHON
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=BROKEN_PYTHON,
            issue=CorrectionIssueRef(
                message="expected ':'",
                severity="critical",
                line=1,
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is False
    assert validation["issues_new"] == []
    assert validation["issues_remaining"][0]["line"] == 2
    assert "still reported" in validation["summary"]


@pytest.mark.asyncio
async def test_new_medium_finding_fails_validation(session) -> None:
    """A medium regression must fail; only low/info findings are warnings."""
    corrected = HTML_VALID.replace(
        "<p>Hi</p>",
        '<p>Hi</p>\n<img src="photo.png">',
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=HTML_VALID,
            language="html",
            file="index.html",
            issue=CorrectionIssueRef(
                message="Falta um título de nível 2",
                severity="low",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is True
    assert [issue["cause"] for issue in validation["issues_new"]] == ["missing_alt"]
    assert [issue["severity"] for issue in validation["issues_new"]] == ["medium"]
    assert validation["issues_warnings"] == []
    assert "new medium-severity" in validation["summary"]


@pytest.mark.asyncio
async def test_new_low_finding_is_a_warning_and_does_not_fail_validation(
    session,
) -> None:
    """A new low finding is visible as a warning, but the status stays passed."""
    corrected = HTML_VALID.replace(
        "<p>Hi</p>",
        '<p>Hi</p>\n<a href="https://example.com" target="_blank">Site</a>',
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=HTML_VALID,
            language="html",
            file="index.html",
            issue=CorrectionIssueRef(
                message="Falta um título de nível 2",
                severity="low",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "passed"
    assert validation["target_resolved"] is True
    assert validation["issues_new"] == []
    assert [issue["cause"] for issue in validation["issues_warnings"]] == [
        "unsafe_target_blank"
    ]
    assert [issue["severity"] for issue in validation["issues_warnings"]] == ["low"]
    assert "no relevant new finding" in validation["summary"]


@pytest.mark.asyncio
async def test_new_info_finding_is_a_warning_and_does_not_fail_validation(
    session,
) -> None:
    """An unverifiable reference is an info warning, not a regression."""
    corrected = HTML_VALID.replace(
        "<p>Hi</p>",
        '<p>Hi</p>\n<img src="photo.png" alt="Foto">',
    )
    context = CorrectionRepositoryContext(
        paths=["index.html"],
        tree_complete=False,
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=HTML_VALID,
            language="html",
            file="index.html",
            repository_context=context,
            issue=CorrectionIssueRef(
                message="Falta um título de nível 2",
                severity="low",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "passed"
    assert validation["target_resolved"] is True
    assert validation["issues_new"] == []
    assert [issue["cause"] for issue in validation["issues_warnings"]] == [
        "reference_unknown"
    ]
    assert [issue["severity"] for issue in validation["issues_warnings"]] == ["info"]
    assert "no relevant new finding" in validation["summary"]


@pytest.mark.asyncio
async def test_validator_unavailable_after_correction_keeps_baseline_as_remaining(
    session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a validator on the corrected code nothing can be resolved."""
    validator = get_validator("python")
    real_validate = validator.validate

    def failing_validate(source: str, context=None):
        if source == FIXED_PYTHON:
            raise RuntimeError("validator unavailable")
        return real_validate(source, context)

    monkeypatch.setattr(validator, "validate", failing_validate)
    service = _service(session, response=_payload(FIXED_PYTHON))

    correction = await service.create(_request(), user_id="user-1")

    validation = correction.post_validation
    assert validation["status"] == "not_run"
    assert validation["target_resolved"] is False
    assert [issue["cause"] for issue in validation["issues_remaining"]] == [
        "python_syntax"
    ]
    assert "not re-evaluated" in validation["summary"]


@pytest.mark.asyncio
async def test_trailing_newline_only_is_no_effective_change(session) -> None:
    """A diff that only normalises the final newline fixes nothing."""
    service = _service(session, response=_payload(VALID_PYTHON + "\n"))

    correction = await service.create(
        _request(
            source_code=VALID_PYTHON,
            issue=CorrectionIssueRef(
                message="Missing module docstring",
                severity="low",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert correction.corrected_code == VALID_PYTHON + "\n"
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is True
    assert validation["issues_new"] == []
    assert "no effective change" in validation["summary"]


@pytest.mark.asyncio
async def test_advpl_include_is_resolved_with_repository_context(session) -> None:
    """A known include must not be reported as unresolved after correction."""
    source = '#include "totvs.ch"\nUser Function Teste()\nReturn Nil\n'
    corrected = source.replace(
        'Return Nil',
        "    // Ajuste aplicado\nReturn Nil",
    )
    context = CorrectionRepositoryContext(
        paths=["totvs.ch"],
        tree_complete=True,
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=source,
            language="advpl",
            file="src/teste.prw",
            repository_context=context,
            issue=CorrectionIssueRef(
                message="Falta um comentário explicando o fluxo",
                severity="low",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "passed"
    assert validation["issues"] == []
    assert validation["issues_remaining"] == []


@pytest.mark.asyncio
async def test_advpl_include_without_context_stays_an_info_finding(session) -> None:
    """Without repository context the include remains unresolved (info)."""
    source = '#include "totvs.ch"\nUser Function Teste()\nReturn Nil\n'
    corrected = source.replace(
        'Return Nil',
        "    // Ajuste aplicado\nReturn Nil",
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=source,
            language="advpl",
            file="src/teste.prw",
            issue=CorrectionIssueRef(
                message="Falta um comentário explicando o fluxo",
                severity="low",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "passed"
    include_issues = [
        issue
        for issue in validation["issues"]
        if issue.get("cause") == "include_unresolved"
    ]
    assert include_issues != []
    assert include_issues[0]["severity"] == "info"
    assert [issue["cause"] for issue in validation["issues_remaining"]] == [
        "include_unresolved"
    ]


@pytest.mark.asyncio
async def test_html_known_reference_is_not_missing_with_repository_context(
    session,
) -> None:
    """A stylesheet listed in the repository tree is a known reference."""
    corrected = HTML_WITH_STYLESHEET.replace(
        "<p>Hi</p>",
        "<p>Hello</p>",
    )
    context = CorrectionRepositoryContext(
        paths=["styles.css"],
        tree_complete=True,
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create(
        _request(
            source_code=HTML_WITH_STYLESHEET,
            language="html",
            file="index.html",
            repository_context=context,
            issue=CorrectionIssueRef(
                message="Texto de boas-vindas pouco claro",
                severity="low",
            ),
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "passed"
    assert validation["issues"] == []


# ---------------------------------------------------- Fase D: modo full (D1)
THREE_ISSUES_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doc</title>
</head>
<body>
<img src="a.png">
<img src="b.png">
<div>
</body>
</html>
"""

THREE_ISSUES_FIXED = """<!DOCTYPE html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doc</title>
</head>
<body>
<img src="a.png" alt="Imagem A">
<img src="b.png" alt="Imagem B">
<div></div>
</body>
</html>
"""

ONE_IMAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doc</title>
</head>
<body>
<p>Hi</p>
<img src="a.png">
</body>
</html>
"""

ONE_IMAGE_WITH_REGRESSION = """<!DOCTYPE html>
<html lang="en">
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doc</title>
</head>
<body>
<p>Hi</p>
<img src="a.png" alt="Imagem A">
<div>
</body>
</html>
"""


def _full_request(
    *,
    source_code: str = THREE_ISSUES_HTML,
    language: str | None = "html",
    file: str | None = "index.html",
    issues: list[CorrectionIssueRef] | None = None,
    analysis_id=None,
    protheus_version: str | None = None,
    repository_context: CorrectionRepositoryContext | None = None,
    mode: str = "full",
) -> CorrectionCreate:
    return CorrectionCreate(
        analysis_id=analysis_id,
        file=file,
        language=language,
        source_code=source_code,
        mode=mode,
        issue=None,
        issues=issues or [],
        protheus_version=protheus_version,
        repository_context=repository_context,
    )


@pytest.mark.asyncio
async def test_full_mode_derives_baseline_issues_and_resolves_all(session) -> None:
    service = _service(session, response=_payload(THREE_ISSUES_FIXED))

    correction = await service.create_full(_full_request(), user_id="user-1")

    assert correction.issue_ref == "full:3"
    assert isinstance(correction.issue, list)
    assert len(correction.issue) == 3
    validation = correction.post_validation
    assert validation["status"] == "passed"
    assert validation["target_resolved"] is True
    assert [issue["cause"] for issue in validation["issues_resolved"]] == [
        "missing_alt",
        "missing_alt",
        "unclosed_tag",
    ]
    assert validation["issues_remaining"] == []
    assert validation["issues_new"] == []
    assert "resolved 3 of 3 target issue(s)" in validation["summary"]
    assert "not an official" in validation["summary"]


@pytest.mark.asyncio
async def test_full_mode_accepts_explicit_issues(session) -> None:
    issues = [
        CorrectionIssueRef(
            message="Image is missing an alt attribute.",
            severity="medium",
            line=8,
            cause="missing_alt",
            code="missing_alt",
        ),
        CorrectionIssueRef(
            message="Image is missing an alt attribute.",
            severity="medium",
            line=9,
            cause="missing_alt",
            code="missing_alt",
        ),
    ]
    corrected = HTML_TWO_IMAGES.replace(
        '<img src="a.png">',
        '<img src="a.png" alt="Imagem A">',
    ).replace(
        '<img src="b.png">',
        '<img src="b.png" alt="Imagem B">',
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create_full(
        _full_request(source_code=HTML_TWO_IMAGES, issues=issues),
        user_id="user-1",
    )

    assert correction.issue_ref == "full:2"
    validation = correction.post_validation
    assert validation["status"] == "passed"
    assert validation["target_resolved"] is True
    assert len(validation["issues_resolved"]) == 2
    assert [issue["cause"] for issue in validation["issues_resolved"]] == [
        "missing_alt",
        "missing_alt",
    ]


@pytest.mark.asyncio
async def test_full_mode_converts_a_single_issue_alias_into_a_target(session) -> None:
    """``mode=full`` plus ``issue`` is convenience for a one-item target list."""
    corrected = ONE_IMAGE_HTML.replace(
        '<img src="a.png">',
        '<img src="a.png" alt="Imagem A">',
    )
    request = CorrectionCreate(
        file="index.html",
        language="html",
        source_code=ONE_IMAGE_HTML,
        mode="full",
        issue=CorrectionIssueRef(
            message="Image is missing an alt attribute.",
            severity="medium",
            line=9,
            cause="missing_alt",
        ),
    )
    assert len(request.issues) == 1
    service = _service(session, response=_payload(corrected))

    correction = await service.create_full(request, user_id="user-1")

    assert correction.issue_ref == "full:1"
    assert correction.post_validation["status"] == "passed"


@pytest.mark.asyncio
async def test_full_mode_partial_correction_fails_with_remaining(session) -> None:
    """Fixing only one of two targets must fail and report the remaining one."""
    corrected = HTML_TWO_IMAGES.replace(
        '<img src="a.png">',
        '<img src="a.png" alt="Imagem A">',
    )
    service = _service(session, response=_payload(corrected))

    correction = await service.create_full(
        _full_request(source_code=HTML_TWO_IMAGES),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is False
    assert [issue["cause"] for issue in validation["issues_resolved"]] == [
        "missing_alt"
    ]
    assert [issue["cause"] for issue in validation["issues_remaining"]] == [
        "missing_alt"
    ]
    assert validation["issues_remaining"][0]["line"] == 9
    assert "1 of 2 target issue(s) are still reported" in validation["summary"]


@pytest.mark.asyncio
async def test_full_mode_regression_fails_validation(session) -> None:
    service = _service(session, response=_payload(ONE_IMAGE_WITH_REGRESSION))

    correction = await service.create_full(
        _full_request(source_code=ONE_IMAGE_HTML),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "failed"
    assert validation["target_resolved"] is True
    assert [issue["cause"] for issue in validation["issues_new"]] == ["unclosed_tag"]
    assert "new high-severity" in validation["summary"]


@pytest.mark.asyncio
async def test_full_mode_invalid_provider_json_is_an_invalid_response(session) -> None:
    service = _service(session, response="not a json payload")

    with pytest.raises(CorrectionInvalidResponseError):
        await service.create_full(_full_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_full_mode_incomplete_provider_is_an_invalid_response(session) -> None:
    service = _service(session, provider=_IncompleteProvider())

    with pytest.raises(CorrectionInvalidResponseError):
        await service.create_full(_full_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_full_mode_timeout_is_a_timeout_error(session) -> None:
    service = _service(
        session,
        provider=_SlowProvider(response=_payload(THREE_ISSUES_FIXED)),
        settings=_settings(llm_timeout_seconds=0.01),
    )

    with pytest.raises(CorrectionTimeoutError):
        await service.create_full(_full_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_full_mode_rejects_more_than_the_configured_limit(session) -> None:
    issues = [
        CorrectionIssueRef(message=f"Problem {index}", severity="low", line=index)
        for index in range(1, 12)
    ]
    service = _service(session, response=_payload(THREE_ISSUES_FIXED))

    with pytest.raises(CorrectionTooManyIssuesError) as excinfo:
        await service.create_full(
            _full_request(issues=issues),
            user_id="user-1",
        )

    assert excinfo.value.count == 11
    assert excinfo.value.limit == 10


@pytest.mark.asyncio
async def test_full_mode_rejects_a_source_without_any_target(session) -> None:
    service = _service(session, response=_payload(VALID_PYTHON))

    with pytest.raises(CorrectionNoIssuesError):
        await service.create_full(
            _full_request(source_code=VALID_PYTHON, language="python", file="src/a.py"),
            user_id="user-1",
        )


@pytest.mark.asyncio
async def test_full_mode_rejects_an_oversized_source(session) -> None:
    service = _service(
        session,
        response=_payload(THREE_ISSUES_FIXED),
        settings=_settings(correction_max_source_bytes=10),
    )

    with pytest.raises(CorrectionSourceTooLargeError):
        await service.create_full(_full_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_full_mode_execution_claim_is_rejected(session) -> None:
    service = _service(
        session,
        response=_payload(
            THREE_ISSUES_FIXED,
            explanation="The corrected file compiles successfully.",
        ),
    )

    with pytest.raises(CorrectionSafetyError):
        await service.create_full(_full_request(), user_id="user-1")


@pytest.mark.asyncio
async def test_full_mode_decision_is_approved_and_rejected(session) -> None:
    service = _service(session, response=_payload(THREE_ISSUES_FIXED))

    approved_correction = await service.create_full(
        _full_request(),
        user_id="user-1",
    )
    approved = await service.decide(
        approved_correction.id,
        "approved",
        user_id="user-1",
    )
    assert approved.status == "approved"
    assert approved.decided_at is not None

    rejected_correction = await service.create_full(
        _full_request(),
        user_id="user-1",
    )
    rejected = await service.decide(
        rejected_correction.id,
        "rejected",
        user_id="user-1",
    )
    assert rejected.status == "rejected"
    assert rejected.decided_at is not None


@pytest.mark.asyncio
async def test_full_mode_prompt_lists_every_target_in_severity_order(session) -> None:
    provider = FakeLLMProvider(response=_payload(THREE_ISSUES_FIXED))
    service = _service(session, provider=provider)

    await service.create_full(_full_request(), user_id="user-1")

    prompt = provider.last_prompt or ""
    assert '"id": 0' in prompt
    assert '"id": 1' in prompt
    assert '"id": 2' in prompt
    # critical/high findings come before medium ones, regardless of input order.
    assert prompt.index('"severity": "high"') < prompt.index('"severity": "medium"')


ELEVEN_IMAGES_HTML = (
    "<!DOCTYPE html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<title>Doc</title>\n"
    "</head>\n"
    "<body>\n"
    + "\n".join(f'<img src="{index}.png">' for index in range(11))
    + "\n</body>\n</html>\n"
)

LOW_REMAINING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<title>Doc</title>
</head>
<body>
<div>
</body>
</html>
"""

LOW_REMAINING_FIXED = """<!DOCTYPE html>
<html lang="en">
<head>
<title>Doc</title>
</head>
<body>
<div></div>
<a href="https://example.com" target="_blank">Site</a>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_full_mode_rejects_a_derived_baseline_above_the_limit(session) -> None:
    """The limit also applies when the targets come from the baseline."""
    service = _service(session, response=_payload(THREE_ISSUES_FIXED))

    with pytest.raises(CorrectionTooManyIssuesError) as excinfo:
        await service.create_full(
            _full_request(source_code=ELEVEN_IMAGES_HTML),
            user_id="user-1",
        )

    assert excinfo.value.count == 11
    assert excinfo.value.limit == 10


@pytest.mark.asyncio
async def test_full_mode_passes_with_low_remaining_and_reports_warnings(
    session,
) -> None:
    """Low/info findings never fail the status; the new one is a warning."""
    service = _service(session, response=_payload(LOW_REMAINING_FIXED))

    correction = await service.create_full(
        _full_request(
            source_code=LOW_REMAINING_HTML,
            issues=[
                CorrectionIssueRef(
                    message="Tag '<div>' is not closed.",
                    severity="high",
                    line=7,
                    cause="unclosed_tag",
                )
            ],
        ),
        user_id="user-1",
    )

    validation = correction.post_validation
    assert validation["status"] == "passed"
    assert validation["target_resolved"] is True
    assert validation["issues_new"] == []
    assert [issue["cause"] for issue in validation["issues_remaining"]] == [
        "missing_viewport"
    ]
    assert [issue["cause"] for issue in validation["issues_warnings"]] == [
        "unsafe_target_blank"
    ]
    assert "original low/info finding(s) remain" in validation["summary"]


@pytest.mark.asyncio
async def test_full_mode_reuses_the_derived_baseline_for_post_validation(
    session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deriving targets validates the original once, not twice."""
    import app.services.correction_service as correction_service_module

    real_validate = correction_service_module.validate_source
    calls: list[str] = []

    def counting_validate(source: str, **kwargs):
        calls.append(source)
        return real_validate(source, **kwargs)

    monkeypatch.setattr(
        correction_service_module,
        "validate_source",
        counting_validate,
    )
    service = _service(session, response=_payload(THREE_ISSUES_FIXED))

    await service.create_full(_full_request(), user_id="user-1")

    # One validation of the original (targets + baseline reuse) and one of the
    # corrected code.
    assert calls == [THREE_ISSUES_HTML, THREE_ISSUES_FIXED]
