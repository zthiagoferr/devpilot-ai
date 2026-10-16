"""Bearer-token verification for authenticated API access.

The module defines the small verification boundary used by the API layer and a
Firebase implementation of it. ``firebase_admin`` is imported lazily, inside the
verifier, so importing the application (or running the test suite) never
requires the dependency, a service account, or any network access.

Failure policy is *fail closed*: every credential that cannot be positively
verified — malformed, expired, revoked, issued by another project, or not
verifiable because the certificate endpoint is unreachable — is rejected with
the same generic error. The caller (``app.api.deps``) turns that into a ``401``.
Tokens and credentials are never logged.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import threading
from typing import Any, Protocol

from app.core.config import get_settings


logger = logging.getLogger("devpilot.auth")

# Every rejection uses the same message so a caller cannot distinguish an
# expired token from a forged one, a revoked token, or a certificate outage.
INVALID_TOKEN_MESSAGE = "Invalid or expired authentication token."

# Small allowance for clock drift between the token issuer and this server.
CLOCK_SKEW_SECONDS = 5

# Firebase application name kept unique so initialization is easy to reason
# about and never collides with another default app in the same process.
_FIREBASE_APP_NAME = "devpilot-ai"


@dataclass(frozen=True)
class VerifiedUser:
    """The identity extracted from a successfully verified bearer token."""

    uid: str
    email: str | None = None
    email_verified: bool = False


class TokenVerificationError(Exception):
    """Raised when a bearer token cannot be positively verified."""

    def __init__(self, message: str = INVALID_TOKEN_MESSAGE) -> None:
        super().__init__(message)


class TokenVerifier(Protocol):
    """Contract implemented by anything able to verify a bearer token."""

    def verify(self, token: str) -> VerifiedUser:
        """Return the verified identity or raise :class:`TokenVerificationError`."""
        ...


class FirebaseTokenVerifier:
    """Verify Firebase ID tokens with the Admin SDK.

    The SDK is imported on first use. ``initialize_app`` runs at most once per
    process, guarded by a lock, and is configured from
    ``FIREBASE_PROJECT_ID`` (and, optionally,
    ``FIREBASE_SERVICE_ACCOUNT_JSON``); when neither is present the verifier
    falls back to Application Default Credentials and still fails closed.
    """

    def __init__(
        self,
        project_id: str | None = None,
        service_account_json: str | None = None,
    ) -> None:
        self._project_id = project_id
        self._service_account_json = service_account_json
        self._lock = threading.Lock()
        self._app: Any = None

    # -- public API ---------------------------------------------------------

    def verify(self, token: str) -> VerifiedUser:
        """Return the identity behind ``token`` or raise the generic error."""
        candidate = (token or "").strip()
        if not candidate:
            raise TokenVerificationError()

        auth_module = self._auth_module()
        if auth_module is None:
            return self._reject("firebase-admin is not available.")

        app = self._firebase_app()
        if app is None:
            return self._reject("the Firebase application is not initialized.")

        try:
            decoded = auth_module.verify_id_token(
                candidate,
                app=app,
                check_revoked=False,
                clock_skew_seconds=CLOCK_SKEW_SECONDS,
            )
        except (
            auth_module.ExpiredIdTokenError,
            auth_module.RevokedIdTokenError,
            auth_module.InvalidIdTokenError,
            auth_module.UserDisabledError,
        ) as exc:
            # Expected rejections: log only the error class, never the token.
            logger.info("Rejected Firebase ID token (%s).", type(exc).__name__)
            raise TokenVerificationError() from None
        except auth_module.CertificateFetchError:
            # The key endpoint is unreachable: reject instead of allowing an
            # unverifiable credential through.
            logger.error(
                "Firebase certificates could not be fetched; "
                "rejecting the bearer token (fail-closed)."
            )
            raise TokenVerificationError() from None
        except Exception as exc:  # noqa: BLE001 - never leak details to callers
            logger.error(
                "Firebase token verification failed (%s); rejecting the bearer token.",
                type(exc).__name__,
            )
            raise TokenVerificationError() from None

        uid = decoded.get("uid") or decoded.get("sub")
        if not uid:
            return self._reject("the verified token carries no subject.")

        email = decoded.get("email")
        return VerifiedUser(
            uid=str(uid),
            email=str(email) if email else None,
            email_verified=bool(decoded.get("email_verified", False)),
        )

    # -- internals ----------------------------------------------------------

    def _reject(self, reason: str) -> VerifiedUser:
        logger.error("Rejecting the bearer token: %s", reason)
        raise TokenVerificationError()

    def _auth_module(self) -> Any:
        """Import ``firebase_admin.auth`` lazily, or return ``None``."""
        try:
            from firebase_admin import auth as firebase_auth
        except ImportError:
            return None
        return firebase_auth

    def _firebase_app(self) -> Any:
        """Return the process-wide Firebase app, initializing it at most once."""
        if self._app is not None:
            return self._app

        with self._lock:
            if self._app is not None:
                return self._app

            try:
                import firebase_admin
                from firebase_admin import credentials
            except ImportError:
                return None

            try:
                self._app = firebase_admin.get_app(_FIREBASE_APP_NAME)
                return self._app
            except ValueError:
                pass

            settings = get_settings()
            project_id = self._project_id or settings.firebase_project_id
            service_account_json = (
                self._service_account_json
                if self._service_account_json is not None
                else _service_account_json_from_settings(settings)
            )

            credential = None
            if service_account_json:
                try:
                    credential = credentials.Certificate(
                        json.loads(service_account_json)
                    )
                except (ValueError, TypeError):
                    logger.error(
                        "FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON; "
                        "rejecting the bearer token (fail-closed)."
                    )
                    return None

            options: dict[str, Any] = {"name": _FIREBASE_APP_NAME}
            if project_id:
                options["projectId"] = project_id

            try:
                self._app = firebase_admin.initialize_app(credential, options)
            except Exception as exc:  # noqa: BLE001 - details stay server-side
                logger.error(
                    "The Firebase application could not be initialized (%s); "
                    "rejecting the bearer token (fail-closed).",
                    type(exc).__name__,
                )
                return None
            return self._app


def _service_account_json_from_settings(settings: Any) -> str | None:
    """Return the configured service account JSON, unredacted or ``None``."""
    secret = getattr(settings, "firebase_service_account_json", None)
    if secret is None:
        return None
    accessor = getattr(secret, "get_secret_value", None)
    value = accessor() if accessor is not None else secret
    if value is None:
        return None
    value = str(value).strip()
    return value or None
