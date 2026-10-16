"""Authentication contract for the analysis endpoints.

Three layers are covered without any Firebase project or network access:

* the verifier itself, with a stand-in Firebase auth module, so every rejection
  path (expired, revoked, foreign project, unreachable certificates) is checked
  against the same generic ``401`` and the token never reaches the logs;
* the HTTP wiring (``require_user`` / ``get_optional_user``), including missing,
  malformed and invalid headers;
* the ownership rules against a real SQLite database: an anonymous submission
  stays public, an authenticated one is owned, and one user can never read
  another user's record (or an anonymous one).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.deps import get_token_verifier
from app.core.auth import (
    INVALID_TOKEN_MESSAGE,
    FirebaseTokenVerifier,
    TokenVerificationError,
    VerifiedUser,
)
from app.db.models import Base
from tests.fake_auth import (
    OTHER_TEST_TOKEN,
    TEST_TOKEN,
    FakeTokenVerifier,
    RejectingTokenVerifier,
    bearer,
)


SOURCE = "def compute_total(items):\n    return sum(items)\n"
PAYLOAD = {
    "task": "code_analysis",
    "project_name": "auth-project",
    "source_code": SOURCE,
}
UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"


# --------------------------------------------------------------------------
# Verifier
# --------------------------------------------------------------------------


class _FakeAuthModule:
    """Minimal stand-in for ``firebase_admin.auth``."""

    class InvalidIdTokenError(Exception):
        pass

    class ExpiredIdTokenError(InvalidIdTokenError):
        pass

    class RevokedIdTokenError(InvalidIdTokenError):
        pass

    class UserDisabledError(Exception):
        pass

    class CertificateFetchError(Exception):
        pass

    def __init__(self, decoded=None, error=None) -> None:
        self.decoded = decoded
        self.error = error
        self.calls: list[dict] = []

    def verify_id_token(
        self,
        token,
        app=None,
        check_revoked=False,
        clock_skew_seconds=0,
    ):
        self.calls.append(
            {
                "token": token,
                "check_revoked": check_revoked,
                "clock_skew_seconds": clock_skew_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        return dict(self.decoded or {})


def _verifier_with(monkeypatch, auth_module) -> FirebaseTokenVerifier:
    verifier = FirebaseTokenVerifier()
    monkeypatch.setattr(verifier, "_auth_module", lambda: auth_module)
    monkeypatch.setattr(verifier, "_firebase_app", lambda: object())
    return verifier


def test_verifier_returns_the_verified_identity(monkeypatch) -> None:
    auth_module = _FakeAuthModule(
        decoded={
            "uid": "user-42",
            "email": "person@example.com",
            "email_verified": True,
        }
    )
    verifier = _verifier_with(monkeypatch, auth_module)

    user = verifier.verify("token-value")

    assert user == VerifiedUser(
        uid="user-42",
        email="person@example.com",
        email_verified=True,
    )
    # Revocation is deliberately not checked (an extra network round trip per
    # request) and a small clock skew is tolerated.
    assert auth_module.calls == [
        {
            "token": "token-value",
            "check_revoked": False,
            "clock_skew_seconds": 5,
        }
    ]


@pytest.mark.parametrize(
    "error_name",
    [
        "InvalidIdTokenError",
        "ExpiredIdTokenError",
        "RevokedIdTokenError",
        "UserDisabledError",
        "CertificateFetchError",
    ],
)
def test_verifier_rejects_every_failure_with_the_generic_error(
    monkeypatch,
    error_name,
) -> None:
    auth_module = _FakeAuthModule(error=getattr(_FakeAuthModule, error_name)("no"))
    verifier = _verifier_with(monkeypatch, auth_module)

    with pytest.raises(TokenVerificationError) as error:
        verifier.verify("token-value")

    assert str(error.value) == INVALID_TOKEN_MESSAGE


def test_verifier_never_logs_the_token(monkeypatch, caplog) -> None:
    secret_token = "super-secret-id-token-value"
    auth_module = _FakeAuthModule(error=_FakeAuthModule.ExpiredIdTokenError("no"))
    verifier = _verifier_with(monkeypatch, auth_module)

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(TokenVerificationError):
            verifier.verify(secret_token)

    assert caplog.text
    assert secret_token not in caplog.text


def test_verifier_fails_closed_when_the_sdk_is_unavailable(
    monkeypatch,
    caplog,
) -> None:
    verifier = FirebaseTokenVerifier()
    monkeypatch.setattr(verifier, "_auth_module", lambda: None)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(TokenVerificationError):
            verifier.verify("token-value")

    assert "firebase-admin" in caplog.text


def test_verifier_rejects_empty_and_subjectless_tokens(monkeypatch) -> None:
    verifier = _verifier_with(monkeypatch, _FakeAuthModule(decoded={"uid": "u"}))

    for token in ("", "   ", None):
        with pytest.raises(TokenVerificationError):
            verifier.verify(token)  # type: ignore[arg-type]

    subjectless = _verifier_with(monkeypatch, _FakeAuthModule(decoded={}))
    with pytest.raises(TokenVerificationError):
        subjectless.verify("token-value")


def test_firebase_sdk_is_imported_lazily() -> None:
    """Importing the module must not require the SDK, credentials or network."""
    import app.core.auth as auth_module

    source = Path(auth_module.__file__).read_text(encoding="utf-8")
    imports = [
        line
        for line in source.splitlines()
        if "firebase_admin" in line
        and line.lstrip().startswith(("import ", "from "))
    ]

    assert imports, "the module is expected to import firebase_admin somewhere"
    for line in imports:
        assert line.startswith((" ", "\t")), f"top-level import found: {line!r}"


# --------------------------------------------------------------------------
# HTTP wiring and ownership
# --------------------------------------------------------------------------


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    """Return a ``TestClient`` over a real SQLite database and fake verifier."""
    from app.db import session as db_session
    from app.main import app

    db_path = tmp_path / "auth.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    original_module_url = db_session.DATABASE_URL

    monkeypatch.setenv("DATABASE_URL", database_url)
    db_session.DATABASE_URL = database_url
    db_session._engine = None
    db_session._session_factory = None

    sync_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    app.dependency_overrides[get_token_verifier] = lambda: FakeTokenVerifier()

    try:
        with TestClient(app) as test_client:
            yield test_client, db_path
    finally:
        app.dependency_overrides.pop(get_token_verifier, None)
        db_session.DATABASE_URL = original_module_url
        db_session._engine = None
        db_session._session_factory = None


def _owners(db_path) -> list[str | None]:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT user_id FROM analyses ORDER BY created_at")
            ).fetchall()
    finally:
        engine.dispose()
    return [row[0] for row in rows]


def test_health_is_available_without_firebase_configuration(monkeypatch) -> None:
    from app.main import app

    for name in (
        "FIREBASE_PROJECT_ID",
        "FIREBASE_SERVICE_ACCOUNT_JSON",
        "FIREBASE_CREDENTIALS",
    ):
        monkeypatch.delenv(name, raising=False)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/").status_code == 200


def test_reads_require_a_token(auth_client) -> None:
    client, _ = auth_client

    listing = client.get("/analyses")
    detail = client.get(f"/analyses/{UNKNOWN_ID}")

    assert listing.status_code == 401
    assert detail.status_code == 401
    assert listing.json()["detail"] == "Authentication required."
    assert listing.headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize(
    "header",
    [
        "Bearer wrong-token",
        "Basic dXNlcjpwYXNz",
        "Bearer",
        "Bearer   ",
        "Token abc",
    ],
)
def test_malformed_or_invalid_headers_are_rejected(auth_client, header) -> None:
    client, _ = auth_client

    headers = {"Authorization": header}
    listing = client.get("/analyses", headers=headers)
    creation = client.post("/analyses", json=PAYLOAD, headers=headers)

    assert listing.status_code == 401, header
    assert creation.status_code == 401, header
    assert "wrong-token" not in creation.text


def test_rejected_verification_is_a_401_not_a_500(tmp_path, monkeypatch) -> None:
    """Expired/revoked/foreign tokens reach the endpoint as a plain 401."""
    from app.db import session as db_session
    from app.main import app

    db_path = tmp_path / "rejected.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    original_module_url = db_session.DATABASE_URL
    monkeypatch.setenv("DATABASE_URL", database_url)
    db_session.DATABASE_URL = database_url
    db_session._engine = None
    db_session._session_factory = None

    app.dependency_overrides[get_token_verifier] = lambda: RejectingTokenVerifier()
    try:
        with TestClient(app) as client:
            listing = client.get("/analyses", headers=bearer("expired"))
            creation = client.post(
                "/analyses",
                json=PAYLOAD,
                headers=bearer("expired"),
            )
    finally:
        app.dependency_overrides.pop(get_token_verifier, None)
        db_session.DATABASE_URL = original_module_url
        db_session._engine = None
        db_session._session_factory = None

    assert listing.status_code == 401
    assert creation.status_code == 401
    assert "expired" not in creation.text


def test_anonymous_submission_stays_public(auth_client) -> None:
    client, db_path = auth_client

    response = client.post("/analyses", json=PAYLOAD)

    assert response.status_code == 201, response.text
    assert "user_id" not in response.json()
    assert _owners(db_path) == [None]


def test_authenticated_submission_is_owned_by_the_token_subject(auth_client) -> None:
    client, db_path = auth_client

    response = client.post(
        "/analyses",
        json={**PAYLOAD, "user_id": "attacker-controlled"},
        headers=bearer(TEST_TOKEN),
    )

    assert response.status_code == 201, response.text
    assert "user_id" not in response.json()
    assert _owners(db_path) == ["user-1"]


def test_history_and_detail_are_scoped_to_the_caller(auth_client) -> None:
    client, _ = auth_client

    mine = client.post("/analyses", json=PAYLOAD, headers=bearer(TEST_TOKEN)).json()
    theirs = client.post(
        "/analyses",
        json=PAYLOAD,
        headers=bearer(OTHER_TEST_TOKEN),
    ).json()
    anonymous = client.post("/analyses", json=PAYLOAD).json()

    listing = client.get("/analyses", headers=bearer(TEST_TOKEN))
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [mine["id"]]

    other_listing = client.get("/analyses", headers=bearer(OTHER_TEST_TOKEN))
    assert [item["id"] for item in other_listing.json()] == [theirs["id"]]

    # Cross-user and anonymous records are invisible: a 404, never a leak.
    for invisible_id in (theirs["id"], anonymous["id"]):
        response = client.get(
            f"/analyses/{invisible_id}",
            headers=bearer(TEST_TOKEN),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Analysis not found"
        assert SOURCE not in response.text

    own_detail = client.get(f"/analyses/{mine['id']}", headers=bearer(TEST_TOKEN))
    assert own_detail.status_code == 200
    assert own_detail.json()["id"] == mine["id"]


def test_anonymous_rows_are_never_listed(auth_client) -> None:
    client, db_path = auth_client

    client.post("/analyses", json=PAYLOAD)
    client.post("/analyses", json=PAYLOAD)

    assert _owners(db_path) == [None, None]
    for token in (TEST_TOKEN, OTHER_TEST_TOKEN):
        response = client.get("/analyses", headers=bearer(token))
        assert response.status_code == 200
        assert response.json() == []


def test_tokens_are_never_logged_during_a_request(auth_client, caplog) -> None:
    client, _ = auth_client

    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/analyses",
            json=PAYLOAD,
            headers=bearer(TEST_TOKEN),
        )

    assert response.status_code == 201
    assert TEST_TOKEN not in caplog.text


@pytest.mark.asyncio
async def test_repository_requires_an_owner_identifier() -> None:
    """The repository refuses an unscoped read instead of listing everything."""
    from types import SimpleNamespace

    from app.db.repositories import AnalysisRepository

    repository = AnalysisRepository(SimpleNamespace())  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        await repository.list_analyses(10, user_id=None)
    with pytest.raises(ValueError):
        await repository.list_analyses(10, user_id="   ")
    with pytest.raises(ValueError):
        await repository.get_by_id(UNKNOWN_ID, user_id=None)  # type: ignore[arg-type]
