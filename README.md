# devpilot-ai

English | [Português](README.pt-BR.md)

🧠 Multi-agent AI platform for intelligent software project analysis.

## Overview

DevPilot discovers a GitHub repository, builds an analysis context, and coordinates specialized agents to produce a structured result. Version 3 adds persistent analysis history through an asynchronous SQLAlchemy persistence layer and HTTP endpoints for creating and retrieving analyses.

## GitHub repository discovery

DevPilot uses a provider abstraction for GitHub access. Application code depends on the provider interface rather than directly on a particular HTTP library, keeping repository discovery replaceable and straightforward to test.

The included implementation uses [`httpx`](https://www.python-httpx.org/) and performs asynchronous GitHub REST API requests. It supports:

- Public repository discovery without credentials.
- Token-authenticated discovery for private repositories or higher GitHub API limits.
- Repository metadata lookup, including the repository's default branch.
- Recursive file-tree discovery from that default branch.
- Configurable GitHub-compatible API endpoints, including GitHub Enterprise Server installations.

The discovery flow is:

1. Request repository metadata from `/repos/{owner}/{repo}`.
2. Read the returned `default_branch` value.
3. Request `/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1`.
4. Return blob entries as repository files while ignoring directory (`tree`) entries.

The provider validates JSON responses and reports HTTP errors or malformed responses instead of silently returning incomplete data.

### Repository and tree limitations

The implementation follows the repository's reported `default_branch`; it does not assume that the branch is named `main` or `master`. A missing default branch is treated as an invalid metadata response.

File discovery uses GitHub's recursive Git tree endpoint. GitHub can set the response's `truncated` field to `true` when a tree is too large to return in one response. Because a truncated result is incomplete, DevPilot rejects it rather than presenting a partial project as complete. Large repositories may therefore need to be narrowed, split into smaller analyses, or handled by a future provider implementation with pagination or alternate traversal.

The current discovery behavior is intentionally limited to the returned tree entries: blob paths are exposed as files, while directory entries are omitted. It does not download file contents, enumerate every historical revision, or automatically traverse additional branches.

## Configuration

Configuration may be supplied through the application's settings system or environment variables.

### GitHub

| Variable | Purpose | Default |
| --- | --- | --- |
| `GITHUB_TOKEN` | Optional personal access token or GitHub App token. If unset, requests are public and omit the `Authorization` header. | Unset |
| `GITHUB_API_BASE_URL` | GitHub REST API base URL override. Use this for GitHub Enterprise Server or a compatible API. | `https://api.github.com` |

The base URL may also be passed directly to the provider as `api_base_url`. It is joined with API paths without changing them, so an override such as `https://github.example.test/api/v3` produces requests under `/api/v3/repos/...`.

### Persistence

Version 3 stores completed analyses in a database through SQLAlchemy's asynchronous engine and session APIs. Set `DATABASE_URL` to the asynchronous database URL for the environment:

```bash
export DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/devpilot"
```

PostgreSQL with [`asyncpg`](https://github.com/MagicStack/asyncpg) is the production configuration. SQLite with [`aiosqlite`](https://github.com/omnilib/aiosqlite) is supported for tests and other applicable local, lightweight scenarios:

```bash
export DATABASE_URL="sqlite+aiosqlite:///./devpilot.db"
```

Do not commit database credentials or other secrets. Use environment variables or deployment secrets, keep local `.env` files out of version control, rotate exposed credentials, and avoid logging request headers or exception details that could disclose them.

### LLM settings

The LLM provider, model, and API key are configured through the application's settings system and environment variables. API keys are treated as secrets and are not included in settings representations or validation errors.

## Version 3 API

The V3 API provides persistent analysis history:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/analyses` | Run an analysis and persist its result. |
| `GET` | `/analyses` | List persisted analyses, newest first. |
| `GET` | `/analyses/{analysis_id}` | Retrieve one persisted analysis by UUID. |

`POST /analyses` validates the request before analysis starts. Invalid or missing request data is rejected with a validation response rather than being persisted. A successful request returns the created analysis, including its generated identifier, result, and creation timestamp.

`GET /analyses` returns records in descending creation-time order. Its `limit` query parameter must be a positive integer and is bounded by the API's configured maximum; values that are zero, negative, non-integer, or above the maximum are rejected. The repository layer also enforces positive limits and applies the bound when querying persistence.

`GET /analyses/{analysis_id}` requires a valid UUID. A malformed identifier is a validation error; a valid identifier that does not exist returns not found. Persistence failures are rolled back so a failed write does not leave a partial analysis record or prevent later writes.

The exact request and response schemas are exposed by the application's generated OpenAPI documentation. When running the development server, use its `/docs` endpoint to inspect the current contract.

## Architecture

The project is organized around clear application boundaries:

- **API layer** — HTTP routes for analysis execution and analysis history.
- **Core configuration** — validated settings and environment-variable integration.
- **Agents** — specialized asynchronous analyzers coordinated by the analysis workflow.
- **Tools** — reusable capabilities such as repository discovery and test execution.
- **GitHub providers** — an interface and an asynchronous `httpx` implementation for repository access.
- **Persistence** — SQLAlchemy models, asynchronous database configuration, and the analysis repository.
- **Migrations** — Alembic revisions for database schema changes.
- **Tests** — unit and asynchronous integration coverage, including an SQLite/`aiosqlite` persistence fixture.

A typical repository layout is:

```text
app/
  agents/
  api/
  core/
  persistence/
  providers/
  tools/
alembic/
tests/
README.md
README.pt-BR.md
```

The names and boundaries above reflect the current architecture; consult the source tree for the definitive module list.

## Installation and setup

Create and activate a virtual environment, then install the project and development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Configure the required application settings and any optional GitHub or database settings in the environment. For local development with SQLite, set `DATABASE_URL` as shown above. For production, use PostgreSQL with `asyncpg` and keep the connection string in a secret-management system.

Start the development API with the project's ASGI entry point:

```bash
uvicorn app.main:app --reload
```

If the distribution does not provide the optional development extra, install the dependencies declared by the project before running the commands above.

## Database migrations

Alembic manages schema changes. Apply all available migrations with:

```bash
alembic upgrade head
```

Create a new migration after changing the SQLAlchemy models with:

```bash
alembic revision --autogenerate -m "describe the schema change"
```

Review autogenerated revisions before committing them. To revert the most recent migration:

```bash
alembic downgrade -1
```

Run migrations against the same `DATABASE_URL` used by the application.

## Testing

Run the complete test suite with:

```bash
python -m pytest
```

The repository also supports:

```bash
pytest
```

Persistence tests use an in-memory SQLite database with `aiosqlite` when the asynchronous SQLAlchemy dependencies are available. The HTTP GitHub provider accepts an injected `httpx.AsyncClient`, allowing tests and callers to provide a custom transport without making real network requests.

## Status and roadmap

- **V1/V2:** GitHub repository discovery, provider abstraction, default-branch handling, recursive tree discovery, authentication, configurable API endpoints, and defensive response validation are available.
- **V3:** Persistent analysis history, asynchronous SQLAlchemy persistence, Alembic migrations, PostgreSQL/`asyncpg` production support, SQLite/`aiosqlite` test support, and the analysis history endpoints are available.
- **Future work:** Large-repository discovery improvements, including pagination or alternate tree traversal, remain roadmap items. The current provider intentionally rejects truncated GitHub tree responses and does not inspect additional branches or historical revisions.

## Security

Never commit tokens, passwords, API keys, or personal credentials to this repository. Supply secrets through environment variables, deployment secrets, or the application's external configuration mechanism. Keep local secret files out of version control, rotate any exposed credential, and avoid printing provider objects, request headers, or exception details that could disclose secrets.
