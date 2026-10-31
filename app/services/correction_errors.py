"""Error contracts shared by the AI correction services.

They live in their own module so the prompt/diff/safety helpers can raise them
without importing the orchestrating service (which imports those helpers), and
are re-exported from :mod:`app.services.correction_service`.
"""

from __future__ import annotations


class CorrectionUnavailableError(RuntimeError):
    """Raised when no AI provider is configured for corrections."""


class CorrectionSourceTooLargeError(ValueError):
    """Raised when the submitted source exceeds the configured limit."""

    def __init__(self, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(
            f"Source code is too large ({size} bytes); the limit is {limit} bytes."
        )


class CorrectionTooManyIssuesError(ValueError):
    """Raised when a full correction exceeds the configured issue limit."""

    def __init__(self, count: int, limit: int) -> None:
        self.count = count
        self.limit = limit
        super().__init__(
            f"Too many issues for a full correction ({count}); "
            f"the limit is {limit}."
        )


class CorrectionNoIssuesError(ValueError):
    """Raised when a full correction has no target issue to address."""

    def __init__(self) -> None:
        super().__init__(
            "No issues to correct: send issues or use a source file whose "
            "baseline validation reports at least one issue."
        )


class CorrectionInvalidResponseError(ValueError):
    """Raised when the provider response is not a usable correction payload."""


class CorrectionSafetyError(ValueError):
    """Raised when a correction makes unsupported execution/compile claims."""


class CorrectionBatchTooManyFilesError(ValueError):
    """Raised when a batch declares more files than the configured limit."""

    def __init__(self, count: int, limit: int) -> None:
        self.count = count
        self.limit = limit
        super().__init__(
            f"Too many files in the batch ({count}); the limit is {limit}."
        )


class CorrectionBatchTooLargeError(ValueError):
    """Raised when the combined batch source exceeds the configured limit."""

    def __init__(self, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(
            f"Batch source is too large ({size} bytes); the limit is {limit} bytes."
        )


class CorrectionBatchInvalidPathError(ValueError):
    """Raised when a batch file path is unsafe (defensive service check)."""


class CorrectionBatchUnsupportedFileError(ValueError):
    """Raised when a batch file path has no supported source extension."""


class CorrectionNotFoundError(LookupError):
    """Raised when a correction (or its analysis) is not visible to the caller."""


class CorrectionStateError(ValueError):
    """Raised when a decision is invalid for the current correction state."""


class CorrectionProviderError(RuntimeError):
    """Raised when the AI provider fails."""


class CorrectionTimeoutError(CorrectionProviderError):
    """Raised when the AI provider does not answer within the configured time."""
