"""Authentication dependencies for the public API.

Two dependencies are exposed:

* :func:`require_user` — the endpoint needs an authenticated caller; a missing
  or invalid ``Authorization`` header is a ``401``.
* :func:`get_optional_user` — the endpoint works for anonymous visitors but
  honours a valid token when one is present; a *present but invalid* header is
  still a ``401`` so a broken session is never silently downgraded to an
  anonymous request.

Token verification is synchronous (it may fetch signing certificates), so it is
executed in the thread pool to avoid blocking the event loop. Neither the token
nor the verification error is ever echoed back to the client.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth import (
    FirebaseTokenVerifier,
    TokenVerificationError,
    TokenVerifier,
    VerifiedUser,
)


UNAUTHENTICATED_DETAIL = "Authentication required."

# ``auto_error=False`` keeps the scheme from answering on its own: a missing
# header must be a decision of each dependency (anonymous allowed or not), and
# a malformed header must produce our generic 401 rather than a 403.
_bearer_scheme = HTTPBearer(auto_error=False)

_token_verifier: TokenVerifier | None = None


def get_token_verifier() -> TokenVerifier:
    """Return the process-wide token verifier (overridable in tests)."""
    global _token_verifier
    if _token_verifier is None:
        _token_verifier = FirebaseTokenVerifier()
    return _token_verifier


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=UNAUTHENTICATED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _verify_credentials(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    verifier: TokenVerifier,
) -> VerifiedUser | None:
    """Return the verified user, ``None`` when no header was sent, or raise 401.

    An ``Authorization`` header that is present but unusable — another scheme,
    or a ``Bearer`` with no token — is rejected instead of being silently
    downgraded to an anonymous request.
    """
    if credentials is None:
        if (request.headers.get("Authorization") or "").strip():
            raise _unauthorized()
        return None

    token = (credentials.credentials or "").strip()
    if not token:
        raise _unauthorized()

    try:
        return await run_in_threadpool(verifier.verify, token)
    except TokenVerificationError:
        raise _unauthorized() from None


async def require_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> VerifiedUser:
    """Require a verified bearer token, answering ``401`` otherwise."""
    user = await _verify_credentials(request, credentials, verifier)
    if user is None:
        raise _unauthorized()
    return user


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> VerifiedUser | None:
    """Return the verified user, or ``None`` for a request without a header."""
    return await _verify_credentials(request, credentials, verifier)
