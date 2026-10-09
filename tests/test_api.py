"""API tests against the real service, repository and database.

The only thing replaced is the request-scoped database session (a standard
FastAPI testing technique).  The service, repository, schemas and orchestrator
are the production implementations, backed by an in-memory SQLite database.
Requests run through ``httpx.ASGITransport`` inside the same event loop as the
database fixture.
"""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.analysis import router as analysis_router
from app.db.models import Base
from app.db.session import get_db_session


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app = FastAPI()
    test_app.include_router(analysis_router)
    test_app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client

    await engine.dispose()


async def _create(client: AsyncClient, **overrides):
    payload = {
        "task": "code",
        "project_name": "devpilot-ai",
        "source_code": "def hello():\n    return 'hello'\n",
    }
    payload.update(overrides)
    return await client.post("/analyses", json=payload)


@pytest.mark.asyncio
async def test_create_analysis_runs_and_persists(client: AsyncClient) -> None:
    response = await _create(client)

    assert response.status_code == 201
    data = response.json()

    UUID(data["id"])
    assert data["task"] == "code"
    assert data["project_name"] == "devpilot-ai"
    assert data["source_code"] == "def hello():\n    return 'hello'\n"
    assert data["status"] == "completed"
    assert data["result"]["agent"] == "code_agent"
    assert data["result"]["score"] == 100


@pytest.mark.asyncio
async def test_list_analyses_returns_persisted_records_newest_first(client: AsyncClient) -> None:
    first = (await _create(client, project_name="first")).json()
    second = (await _create(client, project_name="second")).json()

    response = await client.get("/analyses")

    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data] == [second["id"], first["id"]]


@pytest.mark.asyncio
async def test_list_analyses_respects_limit(client: AsyncClient) -> None:
    await _create(client, project_name="first")
    await _create(client, project_name="second")

    response = await client.get("/analyses?limit=1")

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_list_analyses_rejects_invalid_limits(client: AsyncClient) -> None:
    for limit in (0, -1, 101):
        assert (await client.get(f"/analyses?limit={limit}")).status_code == 422


@pytest.mark.asyncio
async def test_get_analysis_by_uuid(client: AsyncClient) -> None:
    created = (await _create(client)).json()

    response = await client.get(f"/analyses/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_unknown_uuid_returns_not_found(client: AsyncClient) -> None:
    response = await client.get(f"/analyses/{uuid4()}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_analysis_rejects_malformed_uuid(client: AsyncClient) -> None:
    assert (await client.get("/analyses/not-a-uuid")).status_code == 422


@pytest.mark.asyncio
async def test_unknown_task_returns_bad_request(client: AsyncClient) -> None:
    response = await _create(client, task="security")

    assert response.status_code == 400
    assert response.json() == {"detail": "No agent available for task: security"}


@pytest.mark.asyncio
async def test_create_analysis_rejects_missing_required_fields(client: AsyncClient) -> None:
    for payload in (
        {"project_name": "demo", "source_code": "print('hello')"},
        {"task": "code", "source_code": "print('hello')"},
        {"task": "code", "project_name": "demo"},
        {},
    ):
        assert (await client.post("/analyses", json=payload)).status_code == 422


@pytest.mark.asyncio
async def test_create_analysis_rejects_empty_required_strings(client: AsyncClient) -> None:
    for payload in (
        {"task": "code", "project_name": "", "source_code": "print('hello')"},
        {"task": "code", "project_name": "demo", "source_code": ""},
        {"task": "", "project_name": "demo", "source_code": "print('hello')"},
    ):
        assert (await client.post("/analyses", json=payload)).status_code == 422


@pytest.mark.asyncio
async def test_create_analysis_rejects_wrong_field_types(client: AsyncClient) -> None:
    for payload in (
        {"task": "code", "project_name": 123, "source_code": "print('hello')"},
        {"task": "code", "project_name": "demo", "source_code": 123},
        {"task": 123, "project_name": "demo", "source_code": "print('hello')"},
    ):
        assert (await client.post("/analyses", json=payload)).status_code == 422
