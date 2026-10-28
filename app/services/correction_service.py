"""Application service for AI corrections.

The service never executes the analyzed or corrected source. It builds a
deterministic prompt, calls the configured provider with a timeout, validates
the textual payload, and re-runs the local structural validators to report
whether the correction introduces regressions. ``passed`` therefore means
"no regression in the local validator", never an official build result.

Every operation is owner-scoped: a correction owned by somebody else, or by
nobody (an anonymous submission), is reported as not found.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.db.models import AnalysisCorrection
from app.db.repositories import (
    AnalysisRepository,
    CorrectionAlreadyDecidedError,
    CorrectionRepository,
)
from app.languages.base import (
    SUPPORTED_LANGUAGES,
    LanguageIssue,
    UnsupportedLanguageError,
    ValidationContext,
    normalize_severity,
)
from app.languages.detector import detect_language
from app.languages.registry import validate_source
from app.schemas.analysis import AnalysisIssue
from app.schemas.correction import (
    CorrectionCreate,
    CorrectionIssueRef,
    CorrectionResponse,
    PostValidationInfo,
)
from app.services.correction_diff import (
    build_unified_diff,
    export_filename,
    iter_added_lines,
)
from app.services.correction_errors import (
    CorrectionInvalidResponseError,
    CorrectionNotFoundError,
    CorrectionProviderError,
    CorrectionSafetyError,
    CorrectionSourceTooLargeError,
    CorrectionStateError,
    CorrectionUnavailableError,
)
from app.services.correction_prompt import (
    SYSTEM_PROMPT,
    build_prompt,
    parse_response,
)
from app.services.correction_safety import (
    assert_no_execution_claims,
    detect_unverified_totvs_usage,
)
from app.services.llm_service import LLMService


logger = logging.getLogger(__name__)

_HIGH_SEVERITIES = frozenset({"critical", "high", "error"})
_DECISIONS = frozenset({"approved", "rejected"})
_EXPORT_FORMATS = frozenset({"corrected", "diff", "json"})
_UNRESOLVED_LANGUAGE = "unknown"

__all__ = [
    "CorrectionInvalidResponseError",
    "CorrectionNotFoundError",
    "CorrectionProviderError",
    "CorrectionSafetyError",
    "CorrectionService",
    "CorrectionSourceTooLargeError",
    "CorrectionStateError",
    "CorrectionUnavailableError",
    "serialize_correction",
]


def serialize_correction(correction: AnalysisCorrection) -> CorrectionResponse:
    """Return the API representation of a persisted correction."""
    try:
        return CorrectionResponse.model_validate(correction)
    except ValidationError as exc:  # pragma: no cover - defensive
        raise CorrectionStateError(
            "The stored correction cannot be represented."
        ) from exc


class CorrectionService:
    """Coordinate one AI correction attempt and its decisions."""

    def __init__(
        self,
        corrections: CorrectionRepository,
        analyses: AnalysisRepository,
        llm: LLMService | None,
        *,
        settings: Settings | None = None,
        provider_name: str | None = None,
    ) -> None:
        self._corrections = corrections
        self._analyses = analyses
        self._llm = llm
        self._settings = settings
        self._provider_name = provider_name

    # ------------------------------------------------------------------ reads
    def _effective_settings(self) -> Any:
        return self._settings if self._settings is not None else get_settings()

    async def get(
        self,
        correction_id: UUID | str,
        *,
        user_id: str | None,
    ) -> AnalysisCorrection:
        """Return one of the caller's corrections or raise ``404``."""
        identifier = _as_uuid(correction_id)
        if identifier is None:
            raise CorrectionNotFoundError("Correction not found")
        try:
            correction = await self._corrections.get_by_id(
                identifier,
                user_id=user_id,
            )
        except ValueError:
            correction = None
        if correction is None:
            raise CorrectionNotFoundError("Correction not found")
        return correction

    async def list_for_analysis(
        self,
        analysis_id: UUID | str,
        *,
        user_id: str | None,
        limit: int = CorrectionRepository.DEFAULT_LIMIT,
    ) -> list[AnalysisCorrection]:
        """Return the caller's corrections for one of the caller's analyses."""
        owner = (user_id or "").strip()
        identifier = _as_uuid(analysis_id)
        if not owner or identifier is None:
            raise CorrectionNotFoundError("Analysis not found")
        analysis = await self._analyses.get_by_id(identifier, user_id=owner)
        if analysis is None:
            raise CorrectionNotFoundError("Analysis not found")
        return await self._corrections.list_for_analysis(
            identifier,
            user_id=owner,
            limit=limit,
        )

    async def decide(
        self,
        correction_id: UUID | str,
        status: str,
        *,
        user_id: str | None,
    ) -> AnalysisCorrection:
        """Approve or reject a pending correction (idempotent for same status)."""
        normalized = (status or "").strip().lower()
        if normalized not in _DECISIONS:
            raise CorrectionStateError("status must be 'approved' or 'rejected'.")

        identifier = _as_uuid(correction_id)
        if identifier is None:
            raise CorrectionNotFoundError("Correction not found")

        try:
            correction = await self._corrections.decide(
                identifier,
                normalized,
                user_id=user_id,
            )
        except CorrectionAlreadyDecidedError:
            raise CorrectionStateError(
                "The correction has already been decided."
            ) from None
        except ValueError:
            correction = None

        if correction is None:
            raise CorrectionNotFoundError("Correction not found")
        return correction

    async def export(
        self,
        correction_id: UUID | str,
        *,
        user_id: str | None,
        fmt: Literal["corrected", "diff", "json"],
    ) -> tuple[str, str, bytes]:
        """Return ``(content_type, filename, body)`` for a download."""
        if fmt not in _EXPORT_FORMATS:
            raise CorrectionStateError("Unsupported export format.")

        correction = await self.get(correction_id, user_id=user_id)

        if fmt == "corrected":
            # Byte-for-byte the stored code: no normalisation on download.
            return (
                "text/plain; charset=utf-8",
                export_filename(correction.file, correction.language),
                correction.corrected_code.encode("utf-8"),
            )
        if fmt == "diff":
            return (
                "text/x-diff; charset=utf-8",
                export_filename(correction.file, correction.language, "diff"),
                (correction.diff or "").encode("utf-8"),
            )

        payload = serialize_correction(correction)
        return (
            "application/json",
            export_filename(correction.file, correction.language, "json"),
            payload.model_dump_json(indent=2).encode("utf-8"),
        )

    # ----------------------------------------------------------------- create
    async def create(
        self,
        request: CorrectionCreate,
        *,
        user_id: str | None,
    ) -> AnalysisCorrection:
        """Run and persist one correction request."""
        started = time.monotonic()
        settings = self._effective_settings()
        source_code = request.source_code

        self._enforce_source_limit(settings, source_code)
        language = self._resolve_language(request)
        effective_user_id = await self._resolve_owner(request, user_id=user_id)

        if self._llm is None:
            raise CorrectionUnavailableError(
                "AI correction is not configured."
            )

        issue = request.issue
        prompt = build_prompt(
            source_code=source_code,
            language=language,
            file=request.file,
            issue=issue,
            protheus_version=request.protheus_version,
        )

        response = await self._generate(settings, prompt)
        payload = parse_response(
            response.content,
            max_bytes=int(
                getattr(settings, "correction_max_corrected_bytes", 1_000_000)
            ),
            max_explanation_bytes=int(
                getattr(settings, "correction_max_explanation_bytes", 20_000)
            ),
        )

        diff = build_unified_diff(source_code, payload.corrected_code, request.file)
        # The generated file contains the user's original code verbatim, so
        # inspecting it as a whole would reject legitimate corrections whose
        # pre-existing strings/comments mention execution ("Processo executado
        # com sucesso" is a common Protheus message). Only the model's own text
        # is checked: the explanation and the lines it actually added.
        assert_no_execution_claims(
            "\n".join([payload.explanation, *iter_added_lines(diff)])
        )

        post_validation = self._post_validate(
            original=source_code,
            corrected=payload.corrected_code,
            language=language,
            file=request.file,
            protheus_version=request.protheus_version,
            target=issue,
            explanation=payload.explanation,
        )

        model = self._provider_name or getattr(response, "model", None)
        if model is not None:
            model = str(model)[:100]

        correction = await self._corrections.create(
            analysis_id=request.analysis_id,
            user_id=effective_user_id,
            language=language,
            file=request.file,
            issue_ref=_issue_ref(issue),
            issue=issue.model_dump(mode="json"),
            original_code=source_code,
            corrected_code=payload.corrected_code,
            diff=diff,
            explanation=payload.explanation,
            origin="ai",
            model=model,
            protheus_version=request.protheus_version,
            post_validation=post_validation.model_dump(mode="json"),
            status="pending",
        )

        logger.info(
            "correction created id=%s language=%s validation=%s elapsed_ms=%d",
            correction.id,
            language,
            post_validation.status,
            int((time.monotonic() - started) * 1000),
        )
        return correction

    # -------------------------------------------------------------- internals
    @staticmethod
    def _enforce_source_limit(settings: Any, source_code: str) -> None:
        limit = int(
            getattr(settings, "correction_max_source_bytes", 200_000)
        )
        size = len(source_code.encode("utf-8"))
        if size > limit:
            raise CorrectionSourceTooLargeError(size, limit)

    @staticmethod
    def _resolve_language(request: CorrectionCreate) -> str:
        requested = (request.language or "").strip().lower() or None
        if requested == "auto":
            requested = None
        detection = detect_language(
            request.source_code,
            path=request.file,
            requested=requested,
        )
        language = detection.language
        if language == _UNRESOLVED_LANGUAGE or language not in SUPPORTED_LANGUAGES:
            raise UnsupportedLanguageError(requested or language)
        return language

    async def _resolve_owner(
        self,
        request: CorrectionCreate,
        *,
        user_id: str | None,
    ) -> str | None:
        """Return the effective owner after validating analysis ownership."""
        owner = (user_id or "").strip() or None
        if request.analysis_id is None:
            return owner

        # Anonymous analyses are deliberately unrecoverable, so a request
        # without an authenticated caller cannot reference one.
        if owner is None:
            raise CorrectionNotFoundError("Analysis not found")

        try:
            analysis = await self._analyses.get_by_id(
                request.analysis_id,
                user_id=owner,
            )
        except ValueError:
            analysis = None
        if analysis is None:
            raise CorrectionNotFoundError("Analysis not found")

        return owner or analysis.user_id

    async def _generate(self, settings: Any, prompt: str) -> Any:
        timeout = float(getattr(settings, "llm_timeout_seconds", 30.0) or 30.0)
        try:
            return await asyncio.wait_for(
                self._llm.generate(prompt, system_prompt=SYSTEM_PROMPT),
                timeout=timeout,
            )
        except TimeoutError:
            raise CorrectionProviderError(
                "The AI provider timed out while generating the correction."
            ) from None
        except CorrectionUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors are sanitized
            logger.warning(
                "correction provider failed: %s",
                type(exc).__name__,
            )
            raise CorrectionProviderError(
                "The AI provider could not complete the correction."
            ) from None

    def _post_validate(
        self,
        *,
        original: str,
        corrected: str,
        language: str,
        file: str | None,
        protheus_version: str | None,
        target: CorrectionIssueRef,
        explanation: str,
    ) -> PostValidationInfo:
        context = ValidationContext(path=file, protheus_version=protheus_version)
        baseline = validate_source(
            original,
            requested_language=language,
            path=file,
            context=context,
        )
        after = validate_source(
            corrected,
            requested_language=language,
            path=file,
            context=context,
        )

        validator_metadata = (
            after.metadata.get("validator")
            if isinstance(after.metadata, Mapping)
            else None
        )
        after_issues = [AnalysisIssue(**issue.as_dict()) for issue in after.issues]

        if after.language == _UNRESOLVED_LANGUAGE or validator_metadata is None:
            return PostValidationInfo(
                status="not_run",
                target_resolved=False,
                issues=after_issues,
                summary=(
                    "The local structural validator did not run for this "
                    "language, so the correction was not verified. This is not "
                    "an official validation."
                ),
            )

        target_resolved = not any(
            _matches_target(issue, target) for issue in after.issues
        )
        # A Python issue from the CodeAgent carries ``exc.msg``; it may also
        # carry the cause/rule id, but its message still differs from the
        # validator's ("Python syntax error: expected ':'"). Compare the target
        # line against the baseline too.
        if target_resolved:
            high_baseline = [
                issue
                for issue in baseline.issues
                if normalize_severity(issue.severity) in _HIGH_SEVERITIES
            ]
            target_resolved = not any(
                _matches_baseline_target(issue, target, high_baseline)
                for issue in after.issues
            )

        baseline_keys = {_issue_key(issue) for issue in baseline.issues}
        new_errors = [
            issue
            for issue in after.issues
            if normalize_severity(issue.severity) in _HIGH_SEVERITIES
            and _issue_key(issue) not in baseline_keys
        ]
        unverified = detect_unverified_totvs_usage(
            original,
            corrected,
            explanation,
            protheus_version=protheus_version,
        )
        for issue in unverified:
            after_issues.append(AnalysisIssue(**issue.as_dict()))

        # An unchanged file cannot have fixed anything: when the baseline
        # already reported issues, "target not reported" is vacuous.
        unchanged = corrected == original
        unchanged_with_baseline = unchanged and bool(baseline.issues)

        failed = (
            bool(new_errors)
            or bool(unverified)
            or not target_resolved
            or unchanged_with_baseline
        )
        if not failed:
            summary = (
                "Local structural validation no longer reports the target issue "
                "and found no new high-severity findings. This is a deterministic "
                "local check, not an official Protheus validation."
            )
        else:
            reasons: list[str] = []
            if not target_resolved:
                reasons.append(
                    "the target issue is still reported by the local validator"
                )
            if new_errors:
                reasons.append(
                    f"{len(new_errors)} new high-severity finding(s) were introduced"
                )
            if unverified:
                reasons.append(
                    f"{len(unverified)} new TOTVS/Protheus identifier(s) could not "
                    "be verified because no Protheus version was provided"
                )
            if unchanged_with_baseline:
                reasons.append(
                    "the corrected code is identical to the original file, so "
                    "the problem reported in the baseline persists even though "
                    "the target issue was not reported again"
                )
            summary = (
                "Correction failed local validation: "
                + "; ".join(reasons)
                + ". This is a deterministic local check, not an official "
                "Protheus validation."
            )

        return PostValidationInfo(
            status="failed" if failed else "passed",
            target_resolved=target_resolved,
            issues=after_issues,
            summary=summary,
        )


def _as_uuid(value: UUID | str | None) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_text(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.lower().split())


def _issue_ref(issue: CorrectionIssueRef) -> str:
    """Return a bounded, stable reference for the target issue."""
    candidate = (
        (issue.rule_id or "").strip()
        or (issue.code or "").strip()
        or _normalize_text(issue.message)
    )
    slug = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")
    return (slug or "issue")[:64]


def _matches_target(issue: LanguageIssue, target: CorrectionIssueRef) -> bool:
    """Tolerantly match a validator issue against the requested target.

    The target comes from the analysis pipeline and its vocabulary differs from
    the validator's, so a match is any of: same or contained ``rule_id``/cause
    (the target ``code`` carries an alias), or a normalized message that
    contains the other one. The containment covers legacy Python issues whose
    message is only ``exc.msg`` ("expected ':'") while the validator prefixes
    it ("Python syntax error: expected ':'").
    """
    issue_keys = {
        _normalize_text(issue.rule_id),
        _normalize_text(issue.cause),
    }
    issue_keys.discard("")

    target_rule = _normalize_text(target.rule_id)
    if target_rule and target_rule in issue_keys:
        return True

    target_cause = _normalize_text(target.code)
    if target_cause and target_cause in issue_keys:
        return True

    return _similar_message(target.message, issue.message)


def _matches_baseline_target(
    issue: LanguageIssue,
    target: CorrectionIssueRef,
    baseline_high: list[LanguageIssue],
) -> bool:
    """Return whether ``issue`` is the baseline problem on the target line.

    Validators phrase the same problem differently before and after a
    correction attempt. When the target carries a line and the baseline already
    reported a critical/high finding on that same line with a similar message,
    the finding is the same problem rather than a new one.
    """
    if target.line is None or issue.line is None or issue.line != target.line:
        return False
    return any(
        entry.line == target.line
        and _similar_message(entry.message, issue.message)
        for entry in baseline_high
    )


def _similar_message(left: str | None, right: str | None) -> bool:
    """Return whether two messages share a normalized message (either way)."""
    first = _normalize_text(left)
    second = _normalize_text(right)
    if not first or not second:
        return False
    return first == second or first in second or second in first


def _issue_key(issue: LanguageIssue) -> tuple[str, str]:
    return (_normalize_text(issue.rule_id), _normalize_text(issue.message))
