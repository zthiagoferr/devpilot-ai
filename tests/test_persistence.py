"""Persistence tests against the real model and repository on SQLite.

These tests exercise :class:`app.db.models.Analysis` and
:class:`app.db.repositories.AnalysisRepository` directly.  There are no
fallbacks: if the model or repository contract is wrong, the tests fail.
"""

from datetime import datetime, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import Analysis, Base
from app.db.repositories import AnalysisRepository


_SECRET = "persistence-test-secret"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


def _analysis(
    *,
    result=None,
    created_at: datetime | None = None,
    project_name: str = "project",
) -> Analysis:
    values = {
        "task": "code",
        "project_name": project_name,
        "source_code": "print('hello')\n",
        "result": result if result is not None else {"score": 100},
        "status": "completed",
    }
    if created_at is not None:
        values["created_at"] = created_at
    return Analysis(**values)


@pytest.mark.asyncio
async def test_analysis_creation_persists_uuid_result_and_timestamp(session_factory):
    async with session_factory() as session:
        repository = AnalysisRepository(session)
        created = await repository.create(_analysis(result={"score": 97}))
        await session.commit()

        assert isinstance(created.id, UUID)
        assert created.result == {"score": 97}
        assert isinstance(created.created_at, datetime)

        loaded = await repository.get_by_id(created.id)

    assert loaded is not None
    assert loaded.id == created.id
    assert loaded.result == {"score": 97}
    assert loaded.created_at == created.created_at


@pytest.mark.asyncio
async def test_retrieval_by_uuid_returns_none_for_missing_record(session_factory):
    async with session_factory() as session:
        repository = AnalysisRepository(session)
        created = await repository.create(_analysis())
        await session.commit()

        assert await repository.get_by_id(created.id) is not None
        assert await repository.get_by_id(
            UUID("00000000-0000-0000-0000-000000000001")
        ) is None


@pytest.mark.asyncio
async def test_analyses_are_returned_newest_first_and_limit_is_bounded(session_factory):
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    async with session_factory() as session:
        repository = AnalysisRepository(session)
        for offset, value in enumerate(("first", "second", "third")):
            await repository.create(
                _analysis(
                    result={"value": value},
                    created_at=base.replace(minute=offset),
                )
            )
        await session.commit()

        analyses = await repository.list(limit=100)
        assert [item.result["value"] for item in analyses] == [
            "third",
            "second",
            "first",
        ]

        with pytest.raises(ValueError):
            await repository.list(limit=0)
        with pytest.raises(ValueError):
            await repository.list(limit=101)


@pytest.mark.asyncio
async def test_failed_write_rolls_back_and_session_remains_usable(session_factory):
    async with session_factory() as session:
        repository = AnalysisRepository(session)

        with pytest.raises(Exception):
            await repository.create(_analysis(result={"not_json": object()}))
        await session.rollback()

        created = await repository.create(_analysis(result={"after_rollback": True}))
        await session.commit()

        assert await repository.get_by_id(created.id) is not None


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
