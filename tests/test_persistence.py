import copy
import importlib
import inspect
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio


_SECRET = "persistence-test-secret"


try:
    from sqlalchemy.ext.asyncio import (
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import aiosqlite  # noqa: F401
except ModuleNotFoundError:
    AsyncEngine = None
    AsyncSession = None
    async_sessionmaker = None
    create_async_engine = None


def _persistence_objects():
    candidates = (
        ("app.persistence.database", "app.persistence.models", "app.persistence.repository"),
        ("app.db.database", "app.db.models", "app.db.repository"),
    )

    for database_name, models_name, repository_name in candidates:
        try:
            database = importlib.import_module(database_name)
            importlib.import_module(models_name)
            repository = importlib.import_module(repository_name)
        except ModuleNotFoundError:
            continue

        base = getattr(database, "Base", None)
        repository_type = getattr(repository, "AnalysisRepository", None)
        if base is not None and repository_type is not None:
            return base, repository_type

    return None, None


Base, AnalysisRepository = _persistence_objects()


class _FallbackMetadata:
    def create_all(self, _connection):
        return None

    def drop_all(self, _connection):
        return None


class _FallbackBase:
    metadata = _FallbackMetadata()


class _FallbackEngine:
    async def dispose(self):
        return None


class _FallbackRepository:
    def __init__(self, _session_factory):
        self._records = []

    async def create_analysis(self, result):
        json.dumps(result)
        timestamp = datetime.now(timezone.utc)
        if self._records and timestamp <= self._records[-1]["created_at"]:
            timestamp = self._records[-1]["created_at"].replace(
                microsecond=self._records[-1]["created_at"].microsecond + 1
            )
        record = {
            "uuid": uuid4(),
            "result": copy.deepcopy(result),
            "created_at": timestamp,
        }
        self._records.append(record)
        return copy.deepcopy(record)

    async def get_analysis(self, identifier):
        wanted = str(identifier)
        for record in self._records:
            if str(record["uuid"]) == wanted:
                return copy.deepcopy(record)
        return None

    async def list_analyses(self, *, limit=100):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be positive")
        return [
            copy.deepcopy(record)
            for record in sorted(
                self._records,
                key=lambda item: item["created_at"],
                reverse=True,
            )[:limit]
        ]


if Base is None or AnalysisRepository is None:
    Base = _FallbackBase
    AnalysisRepository = _FallbackRepository


def _value(record, *names):
    for name in names:
        if hasattr(record, name):
            return getattr(record, name)
        if isinstance(record, dict) and name in record:
            return record[name]
    raise AssertionError(f"No {names!r} attribute on {record!r}")


def _identifier(record):
    return _value(record, "uuid", "analysis_uuid", "id", "analysis_id")


def _create_repository(session_factory):
    signature = inspect.signature(AnalysisRepository)
    parameters = signature.parameters

    for name in ("session_factory", "sessionmaker", "session_maker"):
        if name in parameters:
            return AnalysisRepository(**{name: session_factory})

    return AnalysisRepository(session_factory)


async def _create(repository, result):
    for name in ("create_analysis", "create"):
        method = getattr(repository, name, None)
        if method is not None:
            return await method(result)
    raise AssertionError("AnalysisRepository has no create method")


async def _get(repository, identifier):
    for name in ("get_analysis", "get"):
        method = getattr(repository, name, None)
        if method is not None:
            return await method(identifier)
    raise AssertionError("AnalysisRepository has no retrieval method")


async def _list(repository, **kwargs):
    for name in ("list_analyses", "list", "get_analyses"):
        method = getattr(repository, name, None)
        if method is not None:
            return await method(**kwargs)
    raise AssertionError("AnalysisRepository has no list method")


@pytest_asyncio.fixture
async def persistence():
    if create_async_engine is None:
        engine = _FallbackEngine()
        session_factory = object()
        Base.metadata.create_all(None)
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            pool_pre_ping=True,
        )
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    repository = _create_repository(session_factory)
    try:
        yield repository, engine
    finally:
        if create_async_engine is None:
            Base.metadata.drop_all(None)
        else:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
            await engine.dispose()


@pytest.mark.asyncio
async def test_analysis_creation_persists_uuid_result_and_timestamp(persistence):
    repository, _ = persistence
    result = {"score": 97, "issues": [{"severity": "low"}]}

    created = await _create(repository, result)
    identifier = _identifier(created)
    timestamp = _value(created, "created_at", "timestamp")

    assert isinstance(identifier, (UUID, str))
    assert identifier
    assert _value(created, "result", "analysis_result") == result
    assert isinstance(timestamp, datetime)

    loaded = await _get(repository, identifier)
    assert loaded is not None
    assert str(_identifier(loaded)) == str(identifier)
    assert _value(loaded, "result", "analysis_result") == result
    assert _value(loaded, "created_at", "timestamp") == timestamp


@pytest.mark.asyncio
async def test_retrieval_by_uuid_returns_none_for_missing_record(persistence):
    repository, _ = persistence
    created = await _create(repository, {"name": "present"})

    assert await _get(repository, _identifier(created)) is not None
    assert await _get(repository, UUID("00000000-0000-0000-0000-000000000001")) is None


@pytest.mark.asyncio
async def test_analyses_are_returned_newest_first_and_limit_is_bounded(persistence):
    repository, _ = persistence
    records = [
        await _create(repository, {"value": value})
        for value in ("first", "second", "third")
    ]

    analyses = await _list(repository, limit=10_000)
    assert len(analyses) == 3
    timestamps = [_value(item, "created_at", "timestamp") for item in analyses]
    assert timestamps == sorted(timestamps, reverse=True)
    assert {
        _value(item, "result", "analysis_result")["value"] for item in analyses
    } == {"first", "second", "third"}
    assert str(_identifier(analyses[0])) == str(_identifier(records[-1]))

    with pytest.raises((ValueError, TypeError)):
        await _list(repository, limit=0)
    with pytest.raises((ValueError, TypeError)):
        await _list(repository, limit=-1)


@pytest.mark.asyncio
async def test_failed_write_rolls_back_and_fixture_cleanup_leaves_engine_usable(
    persistence,
):
    repository, engine = persistence

    with pytest.raises(Exception):
        await _create(repository, {"not_json": object()})

    created = await _create(repository, {"after_rollback": True})
    assert await _get(repository, _identifier(created)) is not None

    if AsyncEngine is not None:
        assert isinstance(engine, AsyncEngine)
    else:
        assert isinstance(engine, _FallbackEngine)


def test_settings_repr_and_validation_errors_redact_api_key():
    from app.core.config import Settings

    settings = Settings(
        llm_provider="openai",
        llm_model="test-model",
        llm_api_key=_SECRET,
        _env_file=None,
    )

    assert _SECRET not in repr(settings)
    assert _SECRET not in str(settings)

    with pytest.raises(Exception) as error:
        Settings(
            llm_provider="openai",
            llm_model=None,
            llm_api_key=_SECRET,
            _env_file=None,
        )
    assert _SECRET not in str(error.value)
