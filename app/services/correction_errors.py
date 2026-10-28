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


class CorrectionInvalidResponseError(ValueError):
    """Raised when the provider response is not a usable correction payload."""


class CorrectionSafetyError(ValueError):
    """Raised when a correction makes unsupported execution/compile claims."""


class CorrectionNotFoundError(LookupError):
    """Raised when a correction (or its analysis) is not visible to the caller."""


class CorrectionStateError(ValueError):
    """Raised when a decision is invalid for the current correction state."""


class CorrectionProviderError(RuntimeError):
    """Raised when the AI provider fails or times out."""
