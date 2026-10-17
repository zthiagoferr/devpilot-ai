"""Fake token verifier shared by the API tests.

The fake implements the same contract as :class:`app.core.auth.TokenVerifier`
and is installed with ``app.dependency_overrides``, so the real authentication
*wiring* (header parsing, 401 decisions, ownership plumbing) is exercised
without any Firebase project or network access.
"""

from __future__ import annotations

from app.core.auth import TokenVerificationError, VerifiedUser


#: Token accepted by :class:`FakeTokenVerifier` for its default user.
TEST_TOKEN = "test-token-user-1"
OTHER_TEST_TOKEN = "test-token-user-2"

DEFAULT_USER = VerifiedUser(
    uid="user-1",
    email="user1@example.com",
    email_verified=True,
)
OTHER_USER = VerifiedUser(
    uid="user-2",
    email="user2@example.com",
    email_verified=True,
)


class FakeTokenVerifier:
    """Accept a fixed set of tokens; reject everything else with the generic error."""

    def __init__(
        self,
        tokens: dict[str, VerifiedUser] | None = None,
    ) -> None:
        self.tokens = dict(
            tokens
            if tokens is not None
            else {TEST_TOKEN: DEFAULT_USER, OTHER_TEST_TOKEN: OTHER_USER}
        )
        #: Every token presented, so a test can assert the raw value never leaks.
        self.seen: list[str] = []

    def verify(self, token: str) -> VerifiedUser:
        self.seen.append(token)
        user = self.tokens.get(token)
        if user is None:
            raise TokenVerificationError()
        return user


class RejectingTokenVerifier:
    """Reject every token, simulating expired/revoked/foreign credentials."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def verify(self, token: str) -> VerifiedUser:
        self.seen.append(token)
        raise TokenVerificationError()


def bearer(token: str) -> dict[str, str]:
    """Return the ``Authorization`` header for ``token``."""
    return {"Authorization": f"Bearer {token}"}
