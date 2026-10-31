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
from app.llm.base import IncompleteLLMResponseError
from app.schemas.analysis import AnalysisIssue
from app.schemas.correction import (
    CorrectionCreate,
    CorrectionIssueRef,
    CorrectionRepositoryContext,
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
from app.services.correction_prompt import (
    FULL_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_full_prompt,
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
#: Severities that make a persisted finding relevant for the status. ``low``
#: and ``info`` remain visible but never turn a correction into ``failed`` on
#: their own; they are reported through ``issues_warnings``.
_RELEVANT_SEVERITIES = frozenset({"critical", "high", "error", "medium"})
_DECISIONS = frozenset({"approved", "rejected"})
_EXPORT_FORMATS = frozenset({"corrected", "diff", "json"})
_UNRESOLVED_LANGUAGE = "unknown"
_NOT_OFFICIAL = (
    "This is a deterministic local check, not an official Protheus validation."
)

#: Line references embedded in validator messages ("opened on line 7",
#: "linha 7-9"). They move whenever unrelated lines are inserted, so they are
#: removed before comparing issue identity.
_LINE_REFERENCE_RE = re.compile(
    r"\b(?:on\s+)?(?:lines?|linhas?)\s*"
    r"(?:n(?:o|º|°)?\.?\s*)?\d+(?:\s*(?:-|–|to|até|a)\s*\d+)?",
    re.IGNORECASE,
)
#: ``line:column`` pairs (``12:5``) are equally position-dependent.
_LINE_COLUMN_RE = re.compile(r"\b\d+\s*:\s*\d+\b")

__all__ = [
    "CorrectionInvalidResponseError",
    "CorrectionNoIssuesError",
    "CorrectionNotFoundError",
    "CorrectionProviderError",
    "CorrectionSafetyError",
    "CorrectionService",
    "CorrectionSourceTooLargeError",
    "CorrectionStateError",
    "CorrectionTimeoutError",
    "CorrectionTooManyIssuesError",
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
        """Run and persist one correction request, dispatching on ``mode``."""
        if request.mode == "full":
            return await self.create_full(request, user_id=user_id)
        return await self._create_single(request, user_id=user_id)

    async def _create_single(
        self,
        request: CorrectionCreate,
        *,
        user_id: str | None,
    ) -> AnalysisCorrection:
        """Run and persist a correction that targets exactly one issue."""
        started = time.monotonic()
        settings, source_code, language, effective_user_id = await self._prepare(
            request,
            user_id=user_id,
        )

        issue = request.issue
        if issue is None:  # guarded by CorrectionCreate, kept for type safety
            raise CorrectionStateError("issue is required when mode='single'.")

        prompt = build_prompt(
            source_code=source_code,
            language=language,
            file=request.file,
            issue=issue,
            protheus_version=request.protheus_version,
        )

        response = await self._generate(settings, prompt, language=language)
        payload = self._parse_generated(settings, response)

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
            repository_context=request.repository_context,
            targets=[issue],
            explanation=payload.explanation,
        )

        correction = await self._persist(
            request=request,
            response=response,
            effective_user_id=effective_user_id,
            language=language,
            source_code=source_code,
            payload=payload,
            diff=diff,
            post_validation=post_validation,
            issue_ref=_issue_ref(issue),
            issue_payload=issue.model_dump(mode="json"),
        )

        logger.info(
            "correction created id=%s language=%s mode=single validation=%s "
            "elapsed_ms=%d",
            correction.id,
            language,
            post_validation.status,
            int((time.monotonic() - started) * 1000),
        )
        return correction

    async def create_full(
        self,
        request: CorrectionCreate,
        *,
        user_id: str | None,
    ) -> AnalysisCorrection:
        """Correct every target issue of one file in a single provider call.

        Targets come from the request (``issues``/``issue``) or, when omitted,
        from the deterministic baseline validation of the submitted source.
        The post-validation reuses the same occurrence matching as the
        single-issue flow, but the status requires *all* targets to be resolved.
        """
        started = time.monotonic()
        settings, source_code, language, effective_user_id = await self._prepare(
            request,
            user_id=user_id,
        )
        return await self._run_full(
            request,
            settings=settings,
            source_code=source_code,
            language=language,
            effective_user_id=effective_user_id,
            started=started,
        )

    async def create_full_prevalidated(
        self,
        request: CorrectionCreate,
        *,
        settings: Any,
        source_code: str,
        language: str,
        effective_user_id: str | None,
        timeout_seconds: float | None = None,
    ) -> AnalysisCorrection:
        """Run the full flow for a file a batch already validated.

        The batch validates the owner, provider availability, path, extension,
        and per-file size once; sharing this entry point keeps the LLM prompt,
        safety checks, post-validation, and persistence identical to the public
        ``full`` mode instead of duplicating them. ``timeout_seconds`` lets the
        batch bound the call by its remaining wall-clock budget.
        """
        return await self._run_full(
            request,
            settings=settings,
            source_code=source_code,
            language=language,
            effective_user_id=effective_user_id,
            started=time.monotonic(),
            timeout_seconds=timeout_seconds,
        )

    async def _run_full(
        self,
        request: CorrectionCreate,
        *,
        settings: Any,
        source_code: str,
        language: str,
        effective_user_id: str | None,
        started: float,
        timeout_seconds: float | None = None,
    ) -> AnalysisCorrection:
        """Execute the validated ``full`` flow and persist its correction."""
        targets, baseline_issues = self._full_targets(
            request,
            source_code=source_code,
            language=language,
        )

        limit = int(getattr(settings, "correction_full_max_issues", 10))
        if len(targets) > limit:
            raise CorrectionTooManyIssuesError(len(targets), limit)
        if not targets:
            raise CorrectionNoIssuesError()

        prompt = build_full_prompt(
            source_code=source_code,
            language=language,
            file=request.file,
            issues=targets,
            repository_context=request.repository_context,
            protheus_version=request.protheus_version,
        )

        response = await self._generate(
            settings,
            prompt,
            language=language,
            system_prompt=FULL_SYSTEM_PROMPT,
            timeout_seconds=timeout_seconds,
        )
        payload = self._parse_generated(settings, response)

        diff = build_unified_diff(source_code, payload.corrected_code, request.file)
        assert_no_execution_claims(
            "\n".join([payload.explanation, *iter_added_lines(diff)])
        )

        post_validation = self._post_validate(
            original=source_code,
            corrected=payload.corrected_code,
            language=language,
            file=request.file,
            protheus_version=request.protheus_version,
            repository_context=request.repository_context,
            targets=targets,
            explanation=payload.explanation,
            baseline_issues=baseline_issues,
        )

        correction = await self._persist(
            request=request,
            response=response,
            effective_user_id=effective_user_id,
            language=language,
            source_code=source_code,
            payload=payload,
            diff=diff,
            post_validation=post_validation,
            issue_ref=_full_issue_ref(targets),
            issue_payload=[issue.model_dump(mode="json") for issue in targets],
        )

        logger.info(
            "correction created id=%s language=%s mode=full targets=%d "
            "validation=%s elapsed_ms=%d",
            correction.id,
            language,
            len(targets),
            post_validation.status,
            int((time.monotonic() - started) * 1000),
        )
        return correction

    # -------------------------------------------------------------- internals
    async def _prepare(
        self,
        request: CorrectionCreate,
        *,
        user_id: str | None,
    ) -> tuple[Any, str, str, str | None]:
        """Apply the limits/ownership/provider checks shared by both modes."""
        settings = self._effective_settings()
        source_code = request.source_code
        self._enforce_source_limit(settings, source_code)
        language = self._resolve_language(request)
        effective_user_id = await self.resolve_owner(
            request.analysis_id,
            user_id=user_id,
        )
        self.ensure_available()
        return settings, source_code, language, effective_user_id

    def ensure_available(self) -> None:
        """Raise when no AI provider is configured for corrections."""
        if self._llm is None:
            raise CorrectionUnavailableError("AI correction is not configured.")

    async def resolve_owner(
        self,
        analysis_id: UUID | None,
        *,
        user_id: str | None,
    ) -> str | None:
        """Return the effective owner after validating analysis ownership.

        Shared by the single/full flows and the batch service: the batch checks
        ownership once for all files instead of once per file.
        """
        owner = (user_id or "").strip() or None
        if analysis_id is None:
            return owner

        # Anonymous analyses are deliberately unrecoverable, so a request
        # without an authenticated caller cannot reference one.
        if owner is None:
            raise CorrectionNotFoundError("Analysis not found")

        try:
            analysis = await self._analyses.get_by_id(
                analysis_id,
                user_id=owner,
            )
        except ValueError:
            analysis = None
        if analysis is None:
            raise CorrectionNotFoundError("Analysis not found")

        return owner or analysis.user_id

    def _full_targets(
        self,
        request: CorrectionCreate,
        *,
        source_code: str,
        language: str,
    ) -> tuple[list[CorrectionIssueRef], list[LanguageIssue] | None]:
        """Return the explicit targets, or derive them from the baseline.

        When the targets are derived, the baseline findings are returned too so
        the post-validation does not run the same deterministic validation
        twice over the unchanged original source.
        """
        if request.issues:
            return list(request.issues), None
        if request.issue is not None:
            return [request.issue], None

        baseline = validate_source(
            source_code,
            requested_language=language,
            path=request.file,
            context=_validation_context(
                file=request.file,
                protheus_version=request.protheus_version,
                repository_context=request.repository_context,
            ),
        )
        return (
            [_language_issue_ref(issue) for issue in baseline.issues],
            list(baseline.issues),
        )

    @staticmethod
    def _parse_generated(settings: Any, response: Any) -> Any:
        return parse_response(
            response.content,
            max_bytes=int(
                getattr(settings, "correction_max_corrected_bytes", 1_000_000)
            ),
            max_explanation_bytes=int(
                getattr(settings, "correction_max_explanation_bytes", 20_000)
            ),
        )

    async def _persist(
        self,
        *,
        request: CorrectionCreate,
        response: Any,
        effective_user_id: str | None,
        language: str,
        source_code: str,
        payload: Any,
        diff: str,
        post_validation: PostValidationInfo,
        issue_ref: str,
        issue_payload: dict[str, Any] | list[dict[str, Any]],
    ) -> AnalysisCorrection:
        model = self._provider_name or getattr(response, "model", None)
        if model is not None:
            model = str(model)[:100]

        return await self._corrections.create(
            analysis_id=request.analysis_id,
            user_id=effective_user_id,
            language=language,
            file=request.file,
            issue_ref=issue_ref,
            issue=issue_payload,
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

    async def _generate(
        self,
        settings: Any,
        prompt: str,
        *,
        language: str,
        system_prompt: str = SYSTEM_PROMPT,
        timeout_seconds: float | None = None,
    ) -> Any:
        timeout = float(
            getattr(settings, "llm_timeout_seconds", 90.0) or 90.0
        )
        if timeout_seconds is not None:
            timeout = min(timeout, max(float(timeout_seconds), 0.001))
        try:
            return await asyncio.wait_for(
                self._llm.generate(prompt, system_prompt=system_prompt),
                timeout=timeout,
            )
        except TimeoutError:
            # Sanitized: only the configured timeout and the detected language
            # are logged. The prompt, the source code, and provider output are
            # never written to logs.
            logger.warning(
                "correction provider timed out after %.0fs (language=%s)",
                timeout,
                language,
            )
            raise CorrectionTimeoutError(
                "The AI provider timed out while generating the correction."
            ) from None
        except IncompleteLLMResponseError:
            logger.warning(
                "correction provider returned an incomplete response "
                "(language=%s)",
                language,
            )
            raise CorrectionInvalidResponseError(
                "The AI provider returned an incomplete response."
            ) from None
        except CorrectionUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider errors are sanitized
            logger.warning(
                "correction provider failed: %s (language=%s)",
                type(exc).__name__,
                language,
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
        targets: list[CorrectionIssueRef],
        explanation: str,
        repository_context: CorrectionRepositoryContext | None = None,
        baseline_issues: list[LanguageIssue] | None = None,
    ) -> PostValidationInfo:
        targets = list(targets)
        context = _validation_context(
            file=file,
            protheus_version=protheus_version,
            repository_context=repository_context,
        )
        if baseline_issues is None:
            baseline = validate_source(
                original,
                requested_language=language,
                path=file,
                context=context,
            )
            baseline_issues = list(baseline.issues)
        else:
            # The caller already validated the unchanged original (full mode
            # deriving its targets), so reuse those findings verbatim.
            baseline_issues = list(baseline_issues)
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
        after_issues = [_as_analysis_issue(issue) for issue in after.issues]

        if after.language == _UNRESOLVED_LANGUAGE or validator_metadata is None:
            # Nothing could be compared: every original finding is still
            # "unevaluated" and is surfaced as remaining, never as resolved.
            remaining = [_as_analysis_issue(issue) for issue in baseline_issues]
            for target in targets:
                if not any(
                    _matches_target(issue, target) for issue in baseline_issues
                ):
                    remaining.append(_target_analysis_issue(target))
            return PostValidationInfo(
                status="not_run",
                target_resolved=False,
                issues=after_issues,
                issues_remaining=remaining,
                summary=(
                    "The local structural validator did not run for this "
                    "language, so the correction was not re-evaluated. This is "
                    "not an official validation."
                ),
            )

        after_validator_issues = list(after.issues)
        resolved_indices, remaining_pairs, new_indices = _match_issue_occurrences(
            baseline_issues,
            after_validator_issues,
        )
        remaining_indices = [baseline_index for baseline_index, _ in remaining_pairs]

        target_flags = [
            _target_is_resolved(
                target,
                baseline_issues=baseline_issues,
                remaining_indices=remaining_indices,
                after_issues=after_validator_issues,
                new_indices=new_indices,
            )
            for target in targets
        ]
        unresolved_targets = sum(1 for resolved in target_flags if not resolved)
        target_resolved = bool(targets) and unresolved_targets == 0

        issues_resolved = [
            _as_analysis_issue(baseline_issues[index]) for index in resolved_indices
        ]
        # A remaining finding is reported at its current position: the identity
        # (and the fact that it persists) comes from the original finding, but
        # the line/message shown to the user are the post-correction ones.
        issues_remaining = [
            _as_analysis_issue(after_validator_issues[after_index])
            for _, after_index in sorted(remaining_pairs, key=lambda pair: pair[1])
        ]
        new_language_issues = [
            after_validator_issues[index] for index in new_indices
        ]

        unverified = detect_unverified_totvs_usage(
            original,
            corrected,
            explanation,
            protheus_version=protheus_version,
        )
        for issue in unverified:
            after_issues.append(_as_analysis_issue(issue))

        # Medium findings are regressions too. Low/info findings are kept as
        # warnings (visible, but they do not fail the status on their own).
        relevant_new = [
            issue
            for issue in new_language_issues
            if _is_relevant_severity(issue.severity)
        ]
        warning_new = [
            issue
            for issue in new_language_issues
            if not _is_relevant_severity(issue.severity)
        ]
        # An unverified TOTVS identifier is a safety signal, not a style
        # observation: it keeps failing the status even though it is low.
        relevant_new.extend(unverified)
        issues_new = [_as_analysis_issue(issue) for issue in relevant_new]
        issues_warnings = [_as_analysis_issue(issue) for issue in warning_new]

        # An added/removed trailing newline (or trailing whitespace) produces an
        # empty diff. It cannot fix anything, so it is never a correction.
        no_effective_change = original.rstrip() == corrected.rstrip()
        identical = corrected == original

        relevant_remaining = [
            issue
            for issue in issues_remaining
            if _is_relevant_severity(issue.severity)
        ]
        high_new = [
            issue
            for issue in issues_new
            if normalize_severity(issue.severity) in _HIGH_SEVERITIES
        ]
        medium_new = [
            issue
            for issue in issues_new
            if normalize_severity(issue.severity) == "medium"
        ]

        failed = bool(
            not target_resolved
            or relevant_remaining
            or issues_new
            or no_effective_change
        )

        if not failed:
            if len(targets) > 1:
                summary = _passed_full_summary(
                    target_count=len(targets),
                    resolved_targets=len(targets) - unresolved_targets,
                    resolved_count=len(issues_resolved),
                    remaining_count=len(issues_remaining),
                )
            else:
                summary = _passed_summary(
                    baseline_count=len(baseline_issues),
                    resolved_count=len(issues_resolved),
                    remaining_count=len(issues_remaining),
                )
        else:
            reasons: list[str] = []
            if not target_resolved:
                if len(targets) > 1:
                    reasons.append(
                        f"{unresolved_targets} of {len(targets)} target issue(s) "
                        "are still reported by the local validator"
                    )
                else:
                    reasons.append(
                        "the target issue is still reported by the local validator"
                    )
            if relevant_remaining:
                if target_resolved:
                    reasons.append(
                        "target resolved but "
                        f"{len(relevant_remaining)} original issue(s) remain"
                    )
                else:
                    reasons.append(
                        f"{len(relevant_remaining)} original issue(s) remain"
                    )
            if high_new:
                reasons.append(
                    f"{len(high_new)} new high-severity finding(s) were introduced"
                )
            if medium_new:
                reasons.append(
                    f"{len(medium_new)} new medium-severity finding(s) were introduced"
                )
            if unverified:
                reasons.append(
                    f"{len(unverified)} new TOTVS/Protheus identifier(s) could not "
                    "be verified because no Protheus version was provided"
                )
            if no_effective_change:
                if identical:
                    if baseline_issues:
                        reasons.append(
                            "the corrected code is identical to the original file, so "
                            "the problem reported in the baseline persists even though "
                            "the target issue was not reported again"
                        )
                    else:
                        # With a clean baseline there is no baseline problem to
                        # persist: claiming one would describe a finding the
                        # validator never reported.
                        reasons.append(
                            "the corrected code is identical to the original file, so "
                            "no change was applied and there was no baseline problem "
                            "to resolve"
                        )
                else:
                    reasons.append(
                        "the corrected code has no effective change (only trailing "
                        "whitespace or the final newline differ), so the problem "
                        "reported in the baseline persists"
                    )
            summary = (
                "Correction failed local validation: "
                + "; ".join(reasons)
                + f". {_NOT_OFFICIAL}"
            )

        return PostValidationInfo(
            status="failed" if failed else "passed",
            target_resolved=target_resolved,
            issues=after_issues,
            summary=summary,
            issues_resolved=issues_resolved,
            issues_remaining=issues_remaining,
            issues_new=issues_new,
            issues_warnings=issues_warnings,
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


def _normalize_message_for_identity(value: str | None) -> str:
    """Normalize a message, removing position references.

    Validators embed line numbers in messages ("block opened on line 7"). When
    unrelated lines are inserted the same finding moves, so the raw message
    changes. Removing ``line N``/``linha N`` and ``line:column`` makes the
    identity stable: a moved issue is not a new issue.
    """
    if not isinstance(value, str):
        return ""
    text = _LINE_REFERENCE_RE.sub(" ", value)
    text = _LINE_COLUMN_RE.sub(" ", text)
    return _normalize_text(text)


def _issue_ref(issue: CorrectionIssueRef) -> str:
    """Return a bounded, stable reference for the target issue."""
    candidate = (
        (issue.rule_id or "").strip()
        or (issue.code or "").strip()
        or _normalize_text(issue.message)
    )
    slug = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")
    return (slug or "issue")[:64]


def _full_issue_ref(issues: list[CorrectionIssueRef]) -> str:
    """Return the persisted reference for a full correction (``full:N``)."""
    return f"full:{len(issues)}"[:64]


def _language_issue_ref(issue: LanguageIssue) -> CorrectionIssueRef:
    """Convert a baseline validator finding into a correction target."""
    return CorrectionIssueRef(
        message=issue.message,
        severity=issue.severity,
        line=issue.line,
        column=issue.column,
        rule_id=issue.rule_id,
        code=issue.code,
        cause=issue.cause,
    )


def _matches_target(issue: LanguageIssue, target: CorrectionIssueRef) -> bool:
    """Tolerantly match a validator issue against the requested target.

    The target comes from the analysis pipeline and its vocabulary differs from
    the validator's, so a match is any of: same or contained ``rule_id``/cause
    (the target ``code``/``cause`` carries an alias), or a normalized message
    that contains the other one. Messages are compared without line numbers, so
    a moved issue still matches. The containment covers legacy Python issues
    whose message is only ``exc.msg`` ("expected ':'") while the validator
    prefixes it ("Python syntax error: expected ':'").
    """
    issue_keys = {
        _normalize_text(issue.rule_id),
        _normalize_text(issue.cause),
    }
    issue_keys.discard("")

    target_rule = _normalize_text(target.rule_id)
    if target_rule and target_rule in issue_keys:
        return True

    for candidate in (
        _normalize_text(target.code),
        _normalize_text(target.cause),
    ):
        if candidate and candidate in issue_keys:
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
    first = _normalize_message_for_identity(left)
    second = _normalize_message_for_identity(right)
    if not first or not second:
        return False
    return first == second or first in second or second in first


def _as_analysis_issue(issue: LanguageIssue) -> AnalysisIssue:
    """Convert a validator finding to its persisted API representation."""
    return AnalysisIssue(**issue.as_dict())


def _target_analysis_issue(target: CorrectionIssueRef) -> AnalysisIssue:
    """Build a representation for a target that the validator never reported."""
    return AnalysisIssue(
        severity=target.severity or "info",
        message=target.message,
        line=target.line,
        column=target.column,
        cause=target.code or target.cause or target.rule_id,
        file=None,
        rule_id=target.rule_id,
        code=target.code,
    )


def _is_relevant_severity(severity: str | None) -> bool:
    """Return whether a finding is relevant for the post-validation status."""
    return normalize_severity(severity) in _RELEVANT_SEVERITIES


def _issue_signature(issue: LanguageIssue) -> str:
    """Return a stable identity for one validator finding.

    Priority: ``rule_id`` (curated rules) -> ``cause`` (validators that tag the
    structural finding) -> severity + normalized message. The message fallback
    keeps legacy findings usable when neither a rule id nor a cause is present;
    it is position-insensitive, like the other keys. Line/column are always
    excluded: moving a line is not a new finding.
    """
    rule_id = _normalize_text(issue.rule_id)
    if rule_id:
        return f"rule:{rule_id}"
    cause = _normalize_text(issue.cause)
    if cause:
        return f"cause:{cause}"
    return (
        f"message:{normalize_severity(issue.severity)}:"
        f"{_normalize_message_for_identity(issue.message)}"
    )


def _match_issue_occurrences(
    baseline: list[LanguageIssue],
    after: list[LanguageIssue],
) -> tuple[list[int], list[tuple[int, int]], list[int]]:
    """Match baseline/after findings by stable identity and occurrence count.

    Returns ``(resolved_indices, remaining_pairs, new_indices)`` where each
    remaining pair is ``(baseline_index, after_index)``. Occurrences are matched
    greedily, preferring the same line and then the nearest line; the line only
    hints which occurrence changed, it is never the identity. Duplicates of the
    same cause (two images without ``alt``) are therefore counted: an extra
    occurrence is new, a missing one is resolved.
    """
    by_signature: dict[str, list[int]] = {}
    for index, issue in enumerate(baseline):
        by_signature.setdefault(_issue_signature(issue), []).append(index)

    matched: dict[int, int] = {}
    new_indices: list[int] = []
    for index, issue in enumerate(after):
        candidates = [
            candidate
            for candidate in by_signature.get(_issue_signature(issue), ())
            if candidate not in matched
        ]
        if not candidates:
            new_indices.append(index)
            continue
        matched[_pick_occurrence(issue, baseline, candidates)] = index

    resolved = [
        index for index in range(len(baseline)) if index not in matched
    ]
    remaining = sorted(matched.items())
    return resolved, remaining, new_indices


def _pick_occurrence(
    issue: LanguageIssue,
    baseline: list[LanguageIssue],
    candidates: list[int],
) -> int:
    """Pick the baseline occurrence a post-correction finding corresponds to."""
    if issue.line is not None:
        same_line = [
            index for index in candidates if baseline[index].line == issue.line
        ]
        if same_line:
            return same_line[0]
        with_line = [
            index for index in candidates if baseline[index].line is not None
        ]
        if with_line:
            return min(
                with_line,
                key=lambda index: abs((baseline[index].line or 0) - issue.line),
            )
    return candidates[0]


def _target_is_resolved(
    target: CorrectionIssueRef,
    *,
    baseline_issues: list[LanguageIssue],
    remaining_indices: list[int],
    after_issues: list[LanguageIssue],
    new_indices: list[int],
) -> bool:
    """Return whether the requested target is no longer reported.

    The comparison uses the same stable identity as the occurrence matching.
    When the target is one occurrence of a duplicated cause, the line hint
    narrows it down; a *different* remaining occurrence does not keep the
    target unresolved. When the baseline never reported the target (an AI-only
    finding), the fallback compares the target against the post-correction
    findings and the baseline's target line.
    """
    remaining = set(remaining_indices)
    direct = [
        index
        for index, issue in enumerate(baseline_issues)
        if _matches_target(issue, target)
    ]
    if target.line is not None and len(direct) > 1:
        same_line = [
            index
            for index in direct
            if baseline_issues[index].line == target.line
        ]
        if same_line:
            direct = same_line

    if direct:
        if set(direct) & remaining:
            return False
        # A brand-new occurrence on the target line keeps the target reported.
        for index in new_indices:
            issue = after_issues[index]
            if _matches_target(issue, target) and (
                target.line is None
                or issue.line is None
                or issue.line == target.line
            ):
                return False
        return True

    # Legacy behavior: a baseline high finding on the target line is the same
    # problem even when the validator rephrases it after the correction.
    if target.line is not None:
        high_baseline = [
            issue
            for issue in baseline_issues
            if normalize_severity(issue.severity) in _HIGH_SEVERITIES
        ]
        same_line_high = [
            index
            for index, issue in enumerate(baseline_issues)
            if issue.line == target.line
            and normalize_severity(issue.severity) in _HIGH_SEVERITIES
        ]
        if same_line_high:
            if set(same_line_high) & remaining:
                return False
            if any(
                _matches_baseline_target(issue, target, high_baseline)
                for issue in after_issues
            ):
                return False

    return not any(_matches_target(issue, target) for issue in after_issues)


def _passed_summary(
    *,
    baseline_count: int,
    resolved_count: int,
    remaining_count: int,
) -> str:
    """Compose the (English) summary of a successful post-validation."""
    if baseline_count:
        head = (
            "Local structural validation resolved "
            f"{resolved_count} of {baseline_count} original finding(s) and "
            "found no relevant new finding."
        )
    else:
        head = (
            "Local structural validation no longer reports the target issue "
            "and found no relevant new finding."
        )
    if remaining_count:
        head += (
            f" {remaining_count} original low/info finding(s) remain as "
            "observations."
        )
    return f"{head} {_NOT_OFFICIAL}"


def _passed_full_summary(
    *,
    target_count: int,
    resolved_targets: int,
    resolved_count: int,
    remaining_count: int,
) -> str:
    """Compose the summary of a successful multi-target post-validation."""
    head = (
        "Local structural validation resolved "
        f"{resolved_targets} of {target_count} target issue(s)"
        + (f" ({resolved_count} original finding(s) in total)" if resolved_count else "")
        + " and found no relevant new finding."
    )
    if remaining_count:
        head += (
            f" {remaining_count} original low/info finding(s) remain as "
            "observations."
        )
    return f"{head} {_NOT_OFFICIAL}"


def _validation_context(
    *,
    file: str | None,
    protheus_version: str | None,
    repository_context: CorrectionRepositoryContext | None,
) -> ValidationContext:
    """Build the reference-check context for both validation passes."""
    paths = repository_context.paths if repository_context is not None else None
    tree_complete = (
        repository_context.tree_complete
        if repository_context is not None
        else True
    )
    truncated = (
        repository_context.truncated
        if repository_context is not None
        else False
    )
    return ValidationContext(
        path=file,
        known_paths=frozenset(paths or []),
        tree_complete=tree_complete,
        truncated=truncated,
        protheus_version=protheus_version,
    )
