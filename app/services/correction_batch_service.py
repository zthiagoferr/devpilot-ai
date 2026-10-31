"""Sequential batch corrections over a bounded set of files.

A batch is deliberately *not* an aggregate entity: every completed file is
persisted as an individual :class:`AnalysisCorrection` (status ``pending``), so
the existing per-file decision endpoint governs approval. The batch adds two
coordination concerns: a shared request budget that keeps total provider time
under the documented proxy limit, preserving whatever was completed when the
budget runs out, and the per-item transaction boundary described below.

Transaction semantics: each completed item is committed immediately, before the
next file is processed. A database failure while persisting item *N* therefore
only invalidates that item: the session is rolled back, the item is reported as
``internal_error``, and items *1..N-1* stay persisted. The final request commit
only closes an empty transaction. This is why "a partial failure preserves the
completed files" also holds for persistence errors, not just for LLM/validation
failures.

Security posture:

* Files are validated before any prompt is built. Sensitive paths (``.env``,
  private keys, ``.git``/``node_modules``) are rejected locally and never reach
  the provider.
* Paths are repository-relative only; ``..``, absolute paths, drive letters, and
  NUL bytes are rejected at the contract boundary and re-checked here.
* Source code and provider payloads are never logged; only the path, the item
  status, and the duration are.
"""

from __future__ import annotations

import logging
import posixpath
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.repository_paths import (
    InvalidRepositoryPathError,
    normalize_repository_path,
)
from app.languages.base import SUPPORTED_LANGUAGES, UnsupportedLanguageError
from app.languages.detector import detect_language, supported_extensions
from app.schemas.correction import (
    CorrectionBatchCreate,
    CorrectionBatchFile,
    CorrectionBatchItem,
    CorrectionBatchResponse,
    CorrectionCreate,
)
from app.services.correction_errors import (
    CorrectionBatchInvalidPathError,
    CorrectionBatchTooLargeError,
    CorrectionBatchTooManyFilesError,
    CorrectionBatchUnsupportedFileError,
    CorrectionInvalidResponseError,
    CorrectionNoIssuesError,
    CorrectionProviderError,
    CorrectionSafetyError,
    CorrectionSourceTooLargeError,
    CorrectionTimeoutError,
    CorrectionTooManyIssuesError,
)
from app.services.correction_service import CorrectionService, serialize_correction


logger = logging.getLogger(__name__)

_UNRESOLVED_LANGUAGE = "unknown"

#: File names that always carry credentials. ``.env.example`` is documentation,
#: not a secret, so it is explicitly allowed.
_SENSITIVE_FILENAMES = frozenset(
    {
        ".env",
        ".netrc",
        ".npmrc",
        ".pgpass",
        "credentials",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
    }
)
_SENSITIVE_PREFIXES = (
    ".env.",
    "credentials.",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
)
#: Documentation/example variants of an env file are safe to send.
_ALLOWED_EXAMPLE_FILES = frozenset(
    {".env.example", ".env.sample", ".env.template"}
)
_SENSITIVE_SUFFIXES = (
    ".jks",
    ".key",
    ".keystore",
    ".p12",
    ".pem",
    ".pfx",
)
_SENSITIVE_DIRECTORIES = frozenset(
    {".aws", ".git", ".gnupg", ".ssh", "node_modules"}
)


def is_sensitive_path(path: str) -> bool:
    """Return whether ``path`` is a credential-bearing file.

    The check is conservative and purely lexical: a matching file is never
    submitted to the LLM, regardless of its content.
    """
    normalized = path.replace("\\", "/").lower()
    name = posixpath.basename(normalized)
    if name in _ALLOWED_EXAMPLE_FILES:
        return False
    if any(part in _SENSITIVE_DIRECTORIES for part in normalized.split("/")[:-1]):
        return True
    if name in _SENSITIVE_FILENAMES:
        return True
    if name.startswith(_SENSITIVE_PREFIXES):
        return True
    return name.endswith(_SENSITIVE_SUFFIXES)


def _extension_of(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


class CorrectionBatchService:
    """Coordinate a bounded, sequential batch of per-file corrections."""

    def __init__(
        self,
        corrections: CorrectionService,
        *,
        session: AsyncSession,
        settings: Settings | None = None,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._corrections = corrections
        # The batch owns the per-item transaction boundary: committing after
        # each completed file is what keeps a later persistence failure from
        # discarding the files already corrected.
        self._session = session
        self._settings = settings
        self._time = time_func

    def _effective_settings(self) -> Any:
        return self._settings if self._settings is not None else get_settings()

    async def create_batch(
        self,
        request: CorrectionBatchCreate,
        *,
        user_id: str | None,
    ) -> CorrectionBatchResponse:
        """Validate the batch, then correct each file under one time budget."""
        started = self._time()
        settings = self._effective_settings()

        requested_language = self._validate_globals(request, settings)
        effective_user_id = await self._corrections.resolve_owner(
            request.analysis_id,
            user_id=user_id,
        )
        self._corrections.ensure_available()

        budget = float(
            getattr(settings, "correction_batch_budget_seconds", 90.0) or 90.0
        )
        llm_timeout = float(
            getattr(settings, "llm_timeout_seconds", 90.0) or 90.0
        )
        deadline = started + max(budget, 0.0)

        results: list[CorrectionBatchItem] = []
        budget_exceeded = False
        for file in request.files:
            if budget_exceeded:
                results.append(
                    _skipped_item(
                        file.path,
                        "budget_exceeded",
                        "The request time budget was exhausted before this file.",
                        reason="budget",
                    )
                )
                continue

            remaining = deadline - self._time()
            if remaining <= 0:
                budget_exceeded = True
                results.append(
                    _skipped_item(
                        file.path,
                        "budget_exceeded",
                        "The request time budget was exhausted before this file.",
                        reason="budget",
                    )
                )
                continue

            item = await self._process_file(
                file,
                request=request,
                settings=settings,
                effective_user_id=effective_user_id,
                requested_language=requested_language,
                timeout_seconds=min(llm_timeout, remaining),
            )
            item = await self._finalize_item(item)
            results.append(item)
            if item.status == "failed" and item.error_code == "timeout":
                # A provider timeout may have consumed the whole budget; the
                # next iteration decides whether the remaining files are
                # skipped. The timeout itself is preserved as a failure.
                if deadline - self._time() <= 0:
                    budget_exceeded = True

        completed = [item for item in results if item.status == "completed"]
        failed = sum(1 for item in results if item.status == "failed")
        skipped = sum(1 for item in results if item.status == "skipped")

        resolved = sum(
            len(item.correction.post_validation.issues_resolved)
            for item in completed
            if item.correction is not None
        )
        remaining_issues = sum(
            len(item.correction.post_validation.issues_remaining)
            for item in completed
            if item.correction is not None
        )
        new_issues = sum(
            len(item.correction.post_validation.issues_new)
            for item in completed
            if item.correction is not None
        )

        logger.info(
            "correction batch finished total=%d completed=%d failed=%d "
            "skipped=%d budget_exceeded=%s elapsed_ms=%d",
            len(results),
            len(completed),
            failed,
            skipped,
            budget_exceeded,
            int((self._time() - started) * 1000),
        )

        return CorrectionBatchResponse(
            results=results,
            files_total=len(results),
            files_completed=len(completed),
            files_failed=failed,
            files_skipped=skipped,
            issues_resolved_total=resolved,
            issues_remaining_total=remaining_issues,
            issues_new_total=new_issues,
            partial=bool(failed or skipped),
            budget_exceeded=budget_exceeded,
        )

    # -------------------------------------------------------------- internals
    async def _finalize_item(self, item: CorrectionBatchItem) -> CorrectionBatchItem:
        """Commit a completed item, isolating it from later failures.

        A persistence error leaves the session's transaction unusable, so the
        failed item first rolls it back and the next file gets a clean
        transaction. Items already committed are untouched.
        """
        if item.status == "completed":
            try:
                await self._session.commit()
            except Exception as exc:  # noqa: BLE001 - the item owns the failure
                # Only the exception type is logged; never the source code.
                logger.warning(
                    "correction batch item commit failed path=%s error=%s",
                    item.path,
                    type(exc).__name__,
                )
                await self._safe_rollback()
                return _failed_item(
                    item.path,
                    "internal_error",
                    500,
                    "The correction could not be persisted for this file.",
                    targeted=item.issues_targeted,
                )
            return item

        if item.reason == "internal_error":
            # The generic handler caught a persistence (or other unexpected)
            # failure. Rolling back restores the session for the next file
            # without touching the items committed so far.
            await self._safe_rollback()
        return item

    async def _safe_rollback(self) -> None:
        try:
            await self._session.rollback()
        except Exception as exc:  # noqa: BLE001 - a broken session must not abort
            logger.warning(
                "correction batch rollback failed error=%s",
                type(exc).__name__,
            )

    def _validate_globals(
        self,
        request: CorrectionBatchCreate,
        settings: Any,
    ) -> str | None:
        """Apply request-wide limits and return the normalized language."""
        max_files = int(getattr(settings, "correction_batch_max_files", 3) or 3)
        if max_files < 1:
            max_files = 1
        if len(request.files) > max_files:
            raise CorrectionBatchTooManyFilesError(len(request.files), max_files)

        max_total = int(
            getattr(settings, "correction_batch_max_total_bytes", None)
            or 3 * int(getattr(settings, "correction_max_source_bytes", 200_000))
        )
        total_bytes = sum(_safe_size(file.source_code) for file in request.files)
        if total_bytes > max_total:
            raise CorrectionBatchTooLargeError(total_bytes, max_total)

        requested = (request.language or "").strip().lower() or None
        if requested == "auto":
            requested = None
        if requested is not None and requested not in SUPPORTED_LANGUAGES:
            raise UnsupportedLanguageError(requested)

        supported = supported_extensions()
        for file in request.files:
            try:
                path = normalize_repository_path(file.path)
            except InvalidRepositoryPathError as exc:
                raise CorrectionBatchInvalidPathError(exc.reason) from None
            # Sensitive paths are handled per item (``sensitive_file``) even
            # when their extension is unsupported (``.env``, ``id_rsa``), so a
            # secret never aborts the other files of the batch. The per-item
            # rejection happens before any prompt is built.
            if is_sensitive_path(path):
                continue
            if _extension_of(path) not in supported:
                raise CorrectionBatchUnsupportedFileError(
                    f"Unsupported file type for batch correction: {path!r}."
                )
        return requested

    async def _process_file(
        self,
        file: CorrectionBatchFile,
        *,
        request: CorrectionBatchCreate,
        settings: Any,
        effective_user_id: str | None,
        requested_language: str | None,
        timeout_seconds: float,
    ) -> CorrectionBatchItem:
        """Validate and correct one file; failures are item-scoped."""
        started = self._time()
        path = file.path

        if is_sensitive_path(path):
            return _failed_item(
                path,
                "sensitive_file",
                422,
                "Sensitive files are never sent to the AI provider.",
            )

        try:
            encoded = file.source_code.encode("utf-8")
        except UnicodeEncodeError:
            return _failed_item(
                path,
                "not_utf8",
                422,
                "The file is not valid UTF-8 text.",
            )
        if "\x00" in file.source_code:
            return _failed_item(
                path,
                "not_utf8",
                422,
                "The file is not valid UTF-8 text.",
            )

        per_file_limit = int(
            getattr(settings, "correction_max_source_bytes", 200_000)
        )
        if len(encoded) > per_file_limit:
            return _failed_item(
                path,
                "source_too_large",
                413,
                f"The file exceeds the per-file limit of {per_file_limit} bytes.",
            )

        detection = detect_language(
            file.source_code,
            path=path,
            requested=requested_language,
        )
        language = detection.language
        if language == _UNRESOLVED_LANGUAGE or language not in SUPPORTED_LANGUAGES:
            return _failed_item(
                path,
                "unsupported_language",
                422,
                "The file language could not be determined.",
            )

        correction_request = CorrectionCreate(
            analysis_id=request.analysis_id,
            file=path,
            language=language,
            source_code=file.source_code,
            mode="full",
            issues=list(file.issues),
            protheus_version=request.protheus_version,
            repository_context=request.repository_context,
        )

        fallback_targets = max(len(file.issues), 0)
        try:
            correction = await self._corrections.create_full_prevalidated(
                correction_request,
                settings=settings,
                source_code=file.source_code,
                language=language,
                effective_user_id=effective_user_id,
                timeout_seconds=timeout_seconds,
            )
        except CorrectionNoIssuesError:
            return _skipped_item(
                path,
                "no_issues",
                "The deterministic baseline found no issue to correct.",
            )
        except CorrectionTooManyIssuesError as exc:
            return _failed_item(
                path,
                "too_many_issues",
                422,
                str(exc),
                targeted=fallback_targets,
            )
        except CorrectionSourceTooLargeError as exc:
            return _failed_item(path, "source_too_large", 413, str(exc))
        except CorrectionTimeoutError:
            return _failed_item(
                path,
                "timeout",
                504,
                "The AI provider timed out for this file.",
                targeted=fallback_targets,
            )
        except CorrectionInvalidResponseError:
            return _failed_item(
                path,
                "invalid_response",
                502,
                "The AI provider returned an invalid response for this file.",
                targeted=fallback_targets,
            )
        except CorrectionSafetyError:
            return _failed_item(
                path,
                "safety_rejected",
                422,
                "The proposed correction was rejected by safety checks.",
                targeted=fallback_targets,
            )
        except CorrectionProviderError:
            return _failed_item(
                path,
                "provider_error",
                502,
                "The AI provider could not complete this file.",
                targeted=fallback_targets,
            )
        except UnsupportedLanguageError:
            return _failed_item(
                path,
                "unsupported_language",
                422,
                "The file language is not supported.",
                targeted=fallback_targets,
            )
        except Exception as exc:  # noqa: BLE001 - one file must not abort the batch
            # Only the exception type is logged: provider payloads and source
            # code stay out of the logs.
            logger.warning(
                "correction batch item failed path=%s error=%s",
                path,
                type(exc).__name__,
            )
            return _failed_item(
                path,
                "internal_error",
                500,
                "The correction could not be completed for this file.",
                targeted=fallback_targets,
            )

        payload = serialize_correction(correction)
        targeted = _target_count(correction, fallback=fallback_targets)
        logger.info(
            "correction batch item path=%s status=completed targets=%d "
            "validation=%s elapsed_ms=%d",
            path,
            targeted,
            payload.post_validation.status,
            int((self._time() - started) * 1000),
        )
        return CorrectionBatchItem(
            path=path,
            status="completed",
            correction=payload,
            issues_targeted=targeted,
        )


def _safe_size(source_code: str) -> int:
    """Return the UTF-8 size, using ``len`` for text that cannot be encoded."""
    try:
        return len(source_code.encode("utf-8"))
    except UnicodeEncodeError:
        # Such a file is rejected per item as ``not_utf8``; the batch total is
        # still bounded so a pathological payload cannot bypass the limit.
        return len(source_code)


def _target_count(correction: Any, *, fallback: int) -> int:
    issue_payload = getattr(correction, "issue", None)
    if isinstance(issue_payload, list):
        return len(issue_payload)
    if isinstance(issue_payload, dict):
        return 1
    return fallback


def _failed_item(
    path: str,
    code: str,
    status: int | None,
    detail: str,
    *,
    targeted: int = 0,
) -> CorrectionBatchItem:
    return CorrectionBatchItem(
        path=path,
        status="failed",
        issues_targeted=targeted,
        error_code=code,
        error_status=status,
        error_detail=detail,
        reason=code,
    )


def _skipped_item(
    path: str,
    code: str,
    detail: str,
    *,
    reason: str | None = None,
) -> CorrectionBatchItem:
    return CorrectionBatchItem(
        path=path,
        status="skipped",
        error_code=code,
        error_detail=detail,
        reason=reason or code,
    )


__all__ = [
    "CorrectionBatchService",
    "is_sensitive_path",
]
