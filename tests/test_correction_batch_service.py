"""Service-level tests for sequential batch corrections (Fase D2a)."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Callable

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.db.models import Base
from app.db.repositories import AnalysisRepository, CorrectionRepository
from app.languages.base import UnsupportedLanguageError
from app.llm.base import LLMProvider, LLMResponse
from app.schemas.correction import (
    CorrectionBatchCreate,
    CorrectionBatchFile,
    CorrectionIssueRef,
    CorrectionRepositoryContext,
)
from app.services.correction_batch_service import (
    CorrectionBatchService,
    is_sensitive_path,
)
from app.services.correction_errors import (
    CorrectionBatchTooLargeError,
    CorrectionBatchTooManyFilesError,
    CorrectionBatchUnsupportedFileError,
    CorrectionNotFoundError,
    CorrectionUnavailableError,
)
from app.services.correction_service import CorrectionService
from app.services.llm_service import LLMService


BROKEN_A = "def alpha(items)\n    return sum(items)\n"
FIXED_A = "def alpha(items):\n    return sum(items)\n"
BROKEN_B = "def beta(items)\n    return sum(items)\n"
FIXED_B = "def beta(items):\n    return sum(items)\n"
BROKEN_C = "def gamma(items)\n    return sum(items)\n"
FIXED_C = "def gamma(items):\n    return sum(items)\n"

HTML_SOURCE = (
    '<!DOCTYPE html>\n<html><body><img src="missing.png"></body></html>\n'
)
HTML_FIXED = (
    '<!DOCTYPE html>\n<html><body><img src="missing.png" alt="Logo">'
    "</body></html>\n"
)

_PROMPT_FILE_RE = re.compile(r"^file: (.+)$", re.MULTILINE)


def _prompt_file(prompt: str) -> str:
    match = _PROMPT_FILE_RE.search(prompt)
    assert match is not None, "batch prompt does not carry the file line"
    return match.group(1).strip()


def _issue() -> CorrectionIssueRef:
    return CorrectionIssueRef(
        message="Python syntax error: expected ':'",
        severity="critical",
        line=1,
        code="python_syntax",
    )


class _MappingProvider(LLMProvider):
    """Return a per-file payload so each item gets its own corrected code."""

    def __init__(
        self,
        mapping: dict[str, str],
        *,
        invalid: set[str] | None = None,
        slow: set[str] | None = None,
        on_generate: Callable[[str], None] | None = None,
        explanations: dict[str, str] | None = None,
    ) -> None:
        self.mapping = mapping
        self.invalid = invalid or set()
        self.slow = slow or set()
        self.on_generate = on_generate
        self.explanations = explanations or {}
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        self.prompts.append(prompt)
        path = _prompt_file(prompt)
        if self.on_generate is not None:
            self.on_generate(path)
        if path in self.slow:
            await asyncio.sleep(0.2)
        if path in self.invalid:
            return LLMResponse(content="not a json payload", model="fake")
        corrected = self.mapping[path]
        content = json.dumps(
            {
                "corrected_code": corrected,
                "explanation": self.explanations.get(path, "Fixed the issue."),
            }
        )
        return LLMResponse(content=content, model="fake")


@pytest_asyncio.fixture()
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'batch.db'}")
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
        project_name="batch-project",
        source_code=BROKEN_A,
        result={"score": 0, "summary": "", "issues": [], "report": {}},
        user_id="user-1",
    )
    await session.commit()
    return record


def _settings(**overrides) -> Settings:
    values = {
        "correction_max_source_bytes": 200_000,
        "correction_max_corrected_bytes": 1_000_000,
        "correction_batch_max_files": 3,
        "correction_batch_budget_seconds": 90.0,
        "llm_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _service(
    session,
    provider: LLMProvider | None,
    *,
    settings: Settings | None = None,
    time_func: Callable[[], float] | None = None,
    llm_none: bool = False,
) -> CorrectionBatchService:
    settings = settings or _settings()
    llm = None if llm_none else LLMService(provider or _MappingProvider({}))
    corrections = CorrectionService(
        CorrectionRepository(session),
        AnalysisRepository(session),
        llm,
        settings=settings,
        provider_name="fake",
    )
    if time_func is None:
        return CorrectionBatchService(corrections, session=session, settings=settings)
    return CorrectionBatchService(
        corrections,
        session=session,
        settings=settings,
        time_func=time_func,
    )


def _file(
    path: str,
    source: str = BROKEN_A,
    *,
    issues: list[CorrectionIssueRef] | None = None,
) -> CorrectionBatchFile:
    return CorrectionBatchFile(
        path=path,
        source_code=source,
        issues=[_issue()] if issues is None else issues,
    )


@pytest.mark.asyncio
async def test_batch_of_three_completes_and_persists_one_correction_per_file(
    session,
    analysis,
) -> None:
    provider = _MappingProvider(
        {
            "src/a.py": FIXED_A,
            "src/b.py": FIXED_B,
            "src/c.py": FIXED_C,
        }
    )
    service = _service(session, provider)
    request = CorrectionBatchCreate(
        analysis_id=analysis.id,
        files=[
            _file("src/a.py", BROKEN_A),
            _file("src/b.py", BROKEN_B),
            _file("src/c.py", BROKEN_C),
        ],
        language="python",
    )

    response = await service.create_batch(request, user_id="user-1")

    assert response.files_total == 3
    assert response.files_completed == 3
    assert response.files_failed == 0
    assert response.files_skipped == 0
    assert response.partial is False
    assert response.budget_exceeded is False
    assert response.issues_resolved_total == 3
    assert response.issues_remaining_total == 0
    assert response.issues_new_total == 0
    assert [item.path for item in response.results] == [
        "src/a.py",
        "src/b.py",
        "src/c.py",
    ]
    assert [item.status for item in response.results] == ["completed"] * 3
    assert len(provider.prompts) == 3

    expected = {
        "src/a.py": (BROKEN_A, FIXED_A),
        "src/b.py": (BROKEN_B, FIXED_B),
        "src/c.py": (BROKEN_C, FIXED_C),
    }
    correction_ids = set()
    for item in response.results:
        assert item.reason is None
        assert item.error_code is None
        correction = item.correction
        assert correction is not None
        original, fixed = expected[item.path]
        assert correction.file == item.path
        assert correction.original_code == original
        assert correction.corrected_code == fixed
        # The diff belongs to the item path, never to another batch file.
        assert correction.diff.startswith(f"--- a/{item.path}")
        assert f"\n+++ b/{item.path}" in correction.diff
        assert correction.post_validation.status == "passed"
        assert correction.status == "pending"
        correction_ids.add(str(correction.id))

    assert len(correction_ids) == 3
    stored = await CorrectionRepository(session).list_for_analysis(
        analysis.id,
        user_id="user-1",
    )
    assert {correction.file for correction in stored} == {
        "src/a.py",
        "src/b.py",
        "src/c.py",
    }


@pytest.mark.asyncio
async def test_sensitive_file_is_failed_without_calling_the_provider(
    session,
) -> None:
    provider = _MappingProvider({"src/a.py": FIXED_A})
    service = _service(session, provider)
    request = CorrectionBatchCreate(
        files=[
            CorrectionBatchFile(
                path=".env",
                source_code="API_KEY=super-secret-value\n",
            ),
            _file("src/a.py", BROKEN_A),
        ],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    assert response.files_completed == 1
    assert response.files_failed == 1
    assert response.partial is True
    sensitive = response.results[0]
    assert sensitive.path == ".env"
    assert sensitive.status == "failed"
    assert sensitive.reason == "sensitive_file"
    assert sensitive.error_code == "sensitive_file"
    assert sensitive.error_status == 422
    assert sensitive.correction is None
    assert "super-secret-value" not in (sensitive.error_detail or "")
    assert len(provider.prompts) == 1
    assert response.results[1].status == "completed"


def test_sensitive_path_detection_covers_credentials_and_examples() -> None:
    assert is_sensitive_path(".env")
    assert is_sensitive_path("config/.env.production")
    assert is_sensitive_path("keys/server.pem")
    assert is_sensitive_path("keys/server.key")
    assert is_sensitive_path("id_rsa")
    assert is_sensitive_path("deploy/id_ed25519.pub")
    assert is_sensitive_path("config/credentials")
    assert is_sensitive_path("certs/client.p12")
    assert is_sensitive_path(".git/config")
    assert not is_sensitive_path(".env.example")
    assert not is_sensitive_path("src/app.py")


@pytest.mark.parametrize(
    "path",
    [
        "../etc/passwd",
        "/etc/passwd",
        "src\\..\\..\\secret.py",
        "src/bad\x00name.py",
        "C:\\repo\\src\\app.py",
    ],
)
def test_unsafe_batch_paths_are_rejected_by_the_contract(path: str) -> None:
    with pytest.raises(ValidationError):
        CorrectionBatchCreate(
            files=[CorrectionBatchFile(path=path, source_code=BROKEN_A)]
        )


def test_backslash_paths_are_normalized_to_posix() -> None:
    batch_file = CorrectionBatchFile(
        path="src\\nested\\app.py",
        source_code=BROKEN_A,
    )

    assert batch_file.path == "src/nested/app.py"


@pytest.mark.asyncio
async def test_oversized_file_fails_alone_without_aborting_the_batch(
    session,
) -> None:
    provider = _MappingProvider({"src/ok.py": FIXED_A})
    service = _service(
        session,
        provider,
        settings=_settings(correction_max_source_bytes=40),
    )
    oversized = "x = 1\n" * 8  # 48 bytes: over the per-file limit (40).
    request = CorrectionBatchCreate(
        files=[
            CorrectionBatchFile(path="src/large.py", source_code=oversized),
            _file("src/ok.py", BROKEN_A),
        ],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    failed = response.results[0]
    assert failed.status == "failed"
    assert failed.reason == "source_too_large"
    assert failed.error_status == 413
    assert response.results[1].status == "completed"
    assert response.partial is True
    # Only the valid file reached the provider.
    assert [_prompt_file(prompt) for prompt in provider.prompts] == ["src/ok.py"]


@pytest.mark.asyncio
async def test_file_over_the_default_200kb_limit_fails_alone(session) -> None:
    provider = _MappingProvider({"src/ok.py": FIXED_A})
    service = _service(session, provider)
    oversized = "x" * 200_001
    request = CorrectionBatchCreate(
        files=[
            CorrectionBatchFile(path="src/large.py", source_code=oversized),
            _file("src/ok.py", BROKEN_A),
        ],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    failed = response.results[0]
    assert failed.status == "failed"
    assert failed.reason == "source_too_large"
    assert failed.error_status == 413
    assert response.results[1].status == "completed"
    assert [_prompt_file(prompt) for prompt in provider.prompts] == ["src/ok.py"]


@pytest.mark.asyncio
async def test_file_without_baseline_issues_is_skipped_without_llm(
    session,
) -> None:
    provider = _MappingProvider({})
    service = _service(session, provider)
    request = CorrectionBatchCreate(
        files=[_file("src/clean.py", "value = 1\n", issues=[])],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    assert response.files_skipped == 1
    assert response.files_completed == 0
    assert response.partial is True
    assert response.budget_exceeded is False
    item = response.results[0]
    assert item.status == "skipped"
    assert item.reason == "no_issues"
    assert item.correction is None
    assert provider.prompts == []


@pytest.mark.asyncio
async def test_null_byte_source_is_failed_as_not_utf8(session) -> None:
    provider = _MappingProvider({})
    service = _service(session, provider)
    request = CorrectionBatchCreate(
        files=[_file("src/binary.py", "x = 1\x00\n")],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    item = response.results[0]
    assert item.status == "failed"
    assert item.reason == "not_utf8"
    assert item.error_status == 422
    assert provider.prompts == []


@pytest.mark.asyncio
async def test_truncated_repository_context_never_reports_a_false_missing(
    session,
) -> None:
    provider = _MappingProvider({"src/page.html": HTML_FIXED})
    service = _service(session, provider)
    request = CorrectionBatchCreate(
        files=[
            _file(
                "src/page.html",
                HTML_SOURCE,
                issues=[
                    CorrectionIssueRef(
                        message="Image is missing an alt attribute.",
                        severity="medium",
                        line=2,
                        code="missing_alt",
                    )
                ],
            )
        ],
        language="html",
        repository_context=CorrectionRepositoryContext(
            paths=["other.html"],
            tree_complete=True,
            truncated=True,
        ),
    )

    response = await service.create_batch(request, user_id=None)

    assert response.results[0].status == "completed"
    correction = response.results[0].correction
    assert correction is not None
    validation = correction.post_validation
    all_issues = [
        *validation.issues_resolved,
        *validation.issues_remaining,
        *validation.issues_new,
        *validation.issues_warnings,
    ]
    causes = [issue.cause for issue in all_issues]
    assert "reference_missing" not in causes
    # The unchecked reference is informational, not a missing-file error.
    assert "reference_unknown" in causes
    assert validation.target_resolved is True
    # The source keeps unrelated baseline findings; only the reference check
    # is under test here, and it must never degrade to a false "missing".
    assert all(issue.cause != "reference_missing" for issue in validation.issues)


@pytest.mark.asyncio
async def test_partial_batch_preserves_completed_corrections(
    session,
    analysis,
) -> None:
    provider = _MappingProvider(
        {"src/a.py": FIXED_A, "src/c.py": FIXED_C},
        invalid={"src/b.py"},
    )
    service = _service(session, provider)
    request = CorrectionBatchCreate(
        analysis_id=analysis.id,
        files=[
            _file("src/a.py", BROKEN_A),
            _file("src/b.py", BROKEN_B),
            _file("src/c.py", BROKEN_C),
        ],
        language="python",
    )

    response = await service.create_batch(request, user_id="user-1")

    assert response.files_total == 3
    assert response.files_completed == 2
    assert response.files_failed == 1
    assert response.partial is True
    assert [item.status for item in response.results] == [
        "completed",
        "failed",
        "completed",
    ]
    failed = response.results[1]
    assert failed.path == "src/b.py"
    assert failed.reason == "invalid_response"
    assert failed.error_status == 502
    assert failed.correction is None

    completed_files = {
        item.correction.file
        for item in response.results
        if item.correction is not None
    }
    assert completed_files == {"src/a.py", "src/c.py"}
    stored = await CorrectionRepository(session).list_for_analysis(
        analysis.id,
        user_id="user-1",
    )
    assert {correction.file for correction in stored} == {
        "src/a.py",
        "src/c.py",
    }


@pytest.mark.asyncio
async def test_budget_exhaustion_skips_only_the_files_not_started(
    session,
    analysis,
) -> None:
    clock = [0.0]

    def advance(path: str) -> None:
        # The first file consumes the whole one-second budget.
        clock[0] = 1.0

    provider = _MappingProvider(
        {"src/a.py": FIXED_A, "src/b.py": FIXED_B},
        on_generate=advance,
    )
    service = _service(
        session,
        provider,
        settings=_settings(correction_batch_budget_seconds=1.0),
        time_func=lambda: clock[0],
    )
    request = CorrectionBatchCreate(
        analysis_id=analysis.id,
        files=[_file("src/a.py", BROKEN_A), _file("src/b.py", BROKEN_B)],
        language="python",
    )

    response = await service.create_batch(request, user_id="user-1")

    assert response.files_completed == 1
    assert response.files_skipped == 1
    assert response.budget_exceeded is True
    assert response.partial is True
    assert response.results[0].status == "completed"
    assert response.results[0].correction is not None
    assert response.results[1].status == "skipped"
    assert response.results[1].reason == "budget"
    assert response.results[1].error_code == "budget_exceeded"
    assert len(provider.prompts) == 1

    stored = await CorrectionRepository(session).list_for_analysis(
        analysis.id,
        user_id="user-1",
    )
    assert [correction.file for correction in stored] == ["src/a.py"]


@pytest.mark.asyncio
async def test_per_file_timeout_fails_that_file_and_continues(
    session,
) -> None:
    provider = _MappingProvider(
        {"src/a.py": FIXED_A, "src/b.py": FIXED_B},
        slow={"src/a.py"},
    )
    service = _service(
        session,
        provider,
        settings=_settings(llm_timeout_seconds=0.01),
    )
    request = CorrectionBatchCreate(
        files=[_file("src/a.py", BROKEN_A), _file("src/b.py", BROKEN_B)],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    assert response.results[0].status == "failed"
    assert response.results[0].reason == "timeout"
    assert response.results[0].error_status == 504
    assert response.results[1].status == "completed"
    assert response.partial is True
    assert response.budget_exceeded is False


@pytest.mark.asyncio
async def test_batch_requires_a_configured_provider(session) -> None:
    service = _service(session, provider=None, llm_none=True)
    request = CorrectionBatchCreate(
        files=[_file("src/a.py", BROKEN_A)],
        language="python",
    )

    with pytest.raises(CorrectionUnavailableError):
        await service.create_batch(request, user_id=None)


@pytest.mark.asyncio
async def test_batch_global_limits_are_enforced(session) -> None:
    service = _service(session, _MappingProvider({}))

    too_many = CorrectionBatchCreate(
        files=[_file(f"src/f{index}.py") for index in range(4)],
        language="python",
    )
    with pytest.raises(CorrectionBatchTooManyFilesError):
        await service.create_batch(too_many, user_id=None)

    too_large = CorrectionBatchCreate(
        files=[
            CorrectionBatchFile(
                path="src/big.py",
                source_code="x" * 70,
                issues=[],
            )
        ],
        language="python",
    )
    limited_service = _service(
        session,
        _MappingProvider({}),
        settings=_settings(correction_max_source_bytes=20),
    )
    with pytest.raises(CorrectionBatchTooLargeError):
        await limited_service.create_batch(too_large, user_id=None)

    invalid_language = CorrectionBatchCreate(
        files=[_file("src/a.py", BROKEN_A)],
        language="cobol",
    )
    with pytest.raises(UnsupportedLanguageError):
        await service.create_batch(invalid_language, user_id=None)

    unsupported_extension = CorrectionBatchCreate(
        files=[_file("src/program.rb", BROKEN_A)],
        language="python",
    )
    with pytest.raises(CorrectionBatchUnsupportedFileError):
        await service.create_batch(unsupported_extension, user_id=None)


@pytest.mark.asyncio
async def test_foreign_analysis_is_not_visible_to_the_caller(
    session,
    analysis,
) -> None:
    service = _service(session, _MappingProvider({"src/a.py": FIXED_A}))
    request = CorrectionBatchCreate(
        analysis_id=analysis.id,
        files=[_file("src/a.py", BROKEN_A)],
        language="python",
    )

    with pytest.raises(CorrectionNotFoundError):
        await service.create_batch(request, user_id="user-2")


@pytest.mark.asyncio
async def test_too_many_issues_fails_the_item_with_its_reason(session) -> None:
    provider = _MappingProvider({"src/a.py": FIXED_A})
    service = _service(
        session,
        provider,
        settings=_settings(correction_full_max_issues=1),
    )
    request = CorrectionBatchCreate(
        files=[
            _file(
                "src/a.py",
                BROKEN_A,
                issues=[
                    _issue(),
                    CorrectionIssueRef(
                        message="Second target",
                        severity="high",
                        line=2,
                    ),
                ],
            )
        ],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    item = response.results[0]
    assert item.status == "failed"
    assert item.reason == "too_many_issues"
    assert item.error_status == 422
    assert item.correction is None
    assert item.issues_targeted == 2
    assert provider.prompts == []


@pytest.mark.asyncio
async def test_safety_rejection_fails_the_item_with_its_reason(session) -> None:
    provider = _MappingProvider(
        {"src/a.py": FIXED_A},
        explanations={"src/a.py": "The corrected code now compiles successfully."},
    )
    service = _service(session, provider)
    request = CorrectionBatchCreate(
        files=[_file("src/a.py", BROKEN_A)],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    item = response.results[0]
    assert item.status == "failed"
    assert item.reason == "safety_rejected"
    assert item.error_status == 422
    assert item.correction is None


@pytest.mark.asyncio
async def test_provider_error_fails_the_item_with_its_reason(session) -> None:
    class _BrokenProvider(LLMProvider):
        async def generate(
            self,
            prompt: str,
            *,
            system_prompt: str | None = None,
        ) -> LLMResponse:
            raise RuntimeError("provider exploded")

    service = _service(session, _BrokenProvider())
    request = CorrectionBatchCreate(
        files=[_file("src/a.py", BROKEN_A)],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    item = response.results[0]
    assert item.status == "failed"
    assert item.reason == "provider_error"
    assert item.error_status == 502
    assert item.correction is None


@pytest.mark.asyncio
async def test_unexpected_error_fails_the_item_as_internal(
    session,
    monkeypatch,
) -> None:
    async def explode(self, *args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(CorrectionService, "create_full_prevalidated", explode)
    service = _service(session, _MappingProvider({"src/a.py": FIXED_A}))
    request = CorrectionBatchCreate(
        files=[_file("src/a.py", BROKEN_A)],
        language="python",
    )

    response = await service.create_batch(request, user_id=None)

    item = response.results[0]
    assert item.status == "failed"
    assert item.reason == "internal_error"
    assert item.error_status == 500
    assert item.correction is None


@pytest.mark.asyncio
async def test_undetectable_language_fails_the_item_with_its_reason(session) -> None:
    # A ``.prg`` file with a C header is deliberately ambiguous, so the
    # detector reports no language instead of guessing.
    c_like_source = '#include <stdio.h>\nint main(void) { printf("hi"); }\n'
    service = _service(session, _MappingProvider({}))
    request = CorrectionBatchCreate(
        files=[
            CorrectionBatchFile(
                path="src/ambiguous.prg",
                source_code=c_like_source,
                issues=[],
            )
        ],
    )

    response = await service.create_batch(request, user_id=None)

    item = response.results[0]
    assert item.status == "failed"
    assert item.reason == "unsupported_language"
    assert item.error_status == 422
    assert item.correction is None


@pytest.mark.asyncio
async def test_duplicate_paths_are_processed_once(session) -> None:
    provider = _MappingProvider({"src/a.py": FIXED_A})
    service = _service(session, provider)
    request = CorrectionBatchCreate(
        files=[
            _file("src/a.py", BROKEN_A),
            _file("src/a.py", BROKEN_A),
        ],
        language="python",
    )

    assert len(request.files) == 1

    response = await service.create_batch(request, user_id=None)

    assert response.files_total == 1
    assert response.files_completed == 1
    assert len(provider.prompts) == 1


@pytest.mark.asyncio
async def test_database_failure_preserves_already_committed_items(
    session,
    analysis,
    monkeypatch,
) -> None:
    """A persistence failure on item 2 must keep item 1 and still run item 3."""
    real_create = CorrectionRepository.create

    async def flaky_create(self, **fields):
        if fields["file"] == "src/b.py":
            # Force a real transaction failure: the NOT NULL constraint makes
            # the session's transaction unusable until it is rolled back.
            await self.session.execute(
                text("INSERT INTO analyses (id) VALUES (NULL)")
            )
        return await real_create(self, **fields)

    monkeypatch.setattr(CorrectionRepository, "create", flaky_create)
    analysis_id = analysis.id
    provider = _MappingProvider(
        {"src/a.py": FIXED_A, "src/b.py": FIXED_B, "src/c.py": FIXED_C},
    )
    service = _service(session, provider)
    request = CorrectionBatchCreate(
        analysis_id=analysis_id,
        files=[
            _file("src/a.py", BROKEN_A),
            _file("src/b.py", BROKEN_B),
            _file("src/c.py", BROKEN_C),
        ],
        language="python",
    )

    response = await service.create_batch(request, user_id="user-1")

    assert [item.status for item in response.results] == [
        "completed",
        "failed",
        "completed",
    ]
    failed = response.results[1]
    assert failed.reason == "internal_error"
    assert failed.error_status == 500

    stored = await CorrectionRepository(session).list_for_analysis(
        analysis_id,
        user_id="user-1",
    )
    # Item 1 was committed before item 2 failed, so the rollback of item 2
    # never discarded it; item 3 was committed afterwards.
    assert {correction.file for correction in stored} == {
        "src/a.py",
        "src/c.py",
    }
