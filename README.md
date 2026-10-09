# DevPilot AI

English | [Português](README.pt-BR.md)

A production-oriented, multi-agent platform for analyzing software projects, coordinating controlled development workflows, and exposing structured results through an API and local dashboard.

## Overview

DevPilot combines specialized agents, explicit tools and skills, GitHub repository discovery, persistent analysis history, and a FastAPI application in one deterministic architecture. The system is designed around reviewed capabilities rather than arbitrary code or shell execution.

The primary analysis workflow coordinates:

- **Code Agent** — analyzes source structure, implementation quality, and code issues.
- **Test Agent** — evaluates tests, assertions, coverage signals, and test structure.
- **Docs Agent** — reviews documentation quality and completeness.
- **Report Agent** — consolidates agent findings into a structured report.
- **Insights Agent** — derives prioritized, actionable project insights.

The platform also includes autonomous workflow agents:

- **Coding Agent** — performs approved, project-scoped coding tasks.
- **Development Agent** — executes a planned sequence of coding tasks with validation and transactional rollback on failure.
- **Planning Agent** — turns development goals into explicit file-level tasks for controlled execution.

Agents are asynchronous and receive explicit context and dependencies. External calls and nondeterministic integrations are replaceable and mocked in tests.

## Architecture

```text
FastAPI API / Dashboard
          |
Application services and orchestration
          |
Specialized analysis and autonomous workflow agents
          |
Skills -> ToolRegistry -> ToolExecutor -> approved tools
          |                         |
       MCP SDK v2                 GitHub provider
          |
SQLAlchemy async persistence -> PostgreSQL / SQLite tests
```

The main boundaries are:

- **API** — analysis, history, repository discovery, health, readiness, and dashboard routes.
- **Agents** — Code, Test, Docs, Report, Insights, Coding, Development, and Planning responsibilities.
- **GitHub provider** — asynchronous `httpx` integration with configurable API endpoints, token support, default-branch discovery, and recursive tree retrieval.
- **Persistence** — asynchronous SQLAlchemy models and repositories, with Alembic-managed schema migrations.
- **Dashboard** — local same-origin HTML, CSS, and JavaScript over the existing API and services.
- **Skills and tools runtime** — explicit registries, deterministic discovery, dependency injection, and safe execution.
- **MCP adapter** — official MCP SDK v2 `MCPServer`/`Client` integration over the canonical tool registry.

## GitHub repository integration

DevPilot uses a provider abstraction so application services do not depend directly on an HTTP client. The included provider supports public repositories, optional token-authenticated access, GitHub Enterprise-compatible base URLs, repository metadata, default-branch lookup, and recursive file-tree discovery.

The provider follows the repository's reported `default_branch`; it does not assume `main` or `master`. Directory entries are omitted and blob entries are returned as files. Truncated GitHub trees are rejected rather than presented as complete. The current integration does not download arbitrary file contents, inspect historical revisions, or traverse additional branches.

## Persistence and database

Completed analyses are persisted with asynchronous SQLAlchemy sessions and repositories. Alembic manages schema changes. **PostgreSQL with `asyncpg` is the production database configuration**; SQLite with `aiosqlite` is supported for deterministic local and test scenarios.

```bash
export DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/devpilot"
# lightweight local/test option
export DATABASE_URL="sqlite+aiosqlite:///./devpilot.db"
```

The history API provides:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/analyses` | Run and persist an analysis. |
| `GET` | `/analyses` | List persisted analyses, newest first. |
| `GET` | `/analyses/{analysis_id}` | Retrieve an analysis by UUID. |

Database write failures roll back transactions so failed operations do not leave partial records or prevent subsequent writes.

## Health and readiness

- `GET /health` is a lightweight **liveness** check. It confirms that the application process is responding and does not require a database query.
- `GET /ready` is the **database readiness** check. It verifies that the configured database can be reached and returns an unavailable response when the application is not ready to serve persistence-dependent traffic.

These endpoints describe application and database state only; they do not provide authentication or deployment orchestration.

## Dashboard

Run the application and open [`http://localhost:8000/dashboard`](http://localhost:8000/dashboard). The dashboard provides local interfaces for submitting analysis input, viewing reports, browsing persisted history, and using repository discovery. It uses the same service layer and API as programmatic clients and does not add unsupported capabilities.

FastAPI serves the dashboard's local static assets. Secrets, database URLs, tokens, and server configuration remain server-side and are never rendered into the page or browser storage.

## Skills and Tools runtime

Tools are explicitly registered capabilities with names, descriptions, JSON-serializable input schemas, and asynchronous execution. Skills group approved tool names for a workflow. `ToolRegistry` and `SkillRegistry` reject invalid or duplicate entries and expose deterministic, sorted metadata. `ToolExecutor` resolves registered tools, validates inputs, applies execution boundaries, and normalizes failures into structured, sanitized results.

The approved runtime can provide narrow capabilities such as project file listing, project-relative reads and writes, repository operations, and bounded test execution. Filesystem tools enforce the configured project root, reject traversal and escaping symlinks, protect sensitive paths such as `.env`, `.git`, and virtual environments, and apply resource limits where configured.

The runtime has no generic shell tool, arbitrary subprocess capability, Python evaluator, unrestricted network client, untrusted dynamic plugin loading, remote code loading, or model-controlled imports. Registration is explicit application code, not directory scanning or package installation. Application-level isolation does not claim to be a VM, container, or complete operating-system security boundary.

## MCP v2 integration

DevPilot integrates the official MCP SDK v2 through `MCPServer` and `Client`. The application creates one canonical, instance-scoped `ToolRegistry` and injects it into the MCP server. MCP discovery and calls therefore expose the same reviewed capabilities as the internal runtime rather than a second hidden registry.

Discovery is deterministic and tool calls return structured JSON-compatible results. Unknown tools fail closed, and internal failures become sanitized MCP errors without stack traces, credentials, environment values, request headers, or sensitive absolute paths. Separate server instances have isolated registries.

V6 MCP is transport-independent and supports in-process SDK testing. It is **not mounted into FastAPI** and does not currently provide an MCP HTTP, socket, or subprocess endpoint. A typical in-process client is:

```python
async with Client(server) as client:
    tools = await client.list_tools()
    result = await client.call_tool("tool_name", {"argument": "value"})
```

## Configuration

Settings are supplied through the application settings system and environment variables. Common variables include:

| Variable | Purpose | Default |
| --- | --- | --- |
| `DATABASE_URL` | Asynchronous SQLAlchemy database URL. | Application default |
| `GITHUB_TOKEN` | Optional GitHub token for private repositories or higher limits. | Unset |
| `GITHUB_API_BASE_URL` | GitHub-compatible REST API base URL. | `https://api.github.com` |
| LLM settings | Provider, model, and API key used by configured analysis workflows. | Application settings |

API keys and connection credentials are excluded from settings representations and validation errors. Use environment or secret-management facilities and keep local secret files out of version control.

## Local setup

```bash
git clone <repository-url>
cd devpilot-ai
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Set the environment for a lightweight local run:

```bash
export DATABASE_URL="sqlite+aiosqlite:///./devpilot.db"
# export GITHUB_TOKEN="..."                 # optional
# export LLM_API_KEY="..."                  # when required by the configured provider
```

Apply migrations and start the development server:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Useful local URLs:

- Dashboard: `http://localhost:8000/dashboard`
- OpenAPI documentation: `http://localhost:8000/docs`
- Liveness: `http://localhost:8000/health`
- Database readiness: `http://localhost:8000/ready`

## Docker and Compose

The repository includes a `Dockerfile` for building the application image and `compose.yaml` for running the application with PostgreSQL. Compose runs **Alembic migrations before application startup**, so the database schema is updated before the API process begins.

```bash
docker compose up --build
```

The Compose configuration is the supported containerized local/production-style configuration in this repository. It does not claim cloud deployment, Kubernetes support, or a distributed execution model.

## Migrations

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe the schema change"
alembic downgrade -1
```

Run Alembic with the same `DATABASE_URL` used by the application. Review autogenerated revisions before committing them.

## Testing and CI

Run the complete deterministic test suite with:

```bash
python -m pytest
```

Tests cover agents, orchestration, API validation, persistence, migrations, dashboard HTML and local assets, filesystem safety, tool and skill registries, executor failures, MCP SDK v2 integration, and health/readiness behavior. GitHub and other external calls use injected clients, transports, or mocks; the suite does not depend on live external services or network state.

GitHub Actions runs the project test suite and its supported checks on repository changes. The workflow is intended to keep builds reproducible and does not deploy the project.

## Security model

Security is enforced at explicit application boundaries:

- **Secret masking:** tokens, API keys, database credentials, authorization headers, environment snapshots, and secret-bearing exception details are excluded from metadata, responses, logs, and errors.
- **Protected filesystem paths:** tools and autonomous coding workflows remain beneath the configured project root and reject traversal, escaping symlinks, `.env`, `.git`, virtual-environment paths, and other protected locations.
- **No arbitrary shell tool:** agents cannot turn model output or a tool argument into a general shell command, unrestricted subprocess, or code evaluator.
- **No untrusted dynamic plugin loading:** tools and skills are explicitly registered application capabilities; the runtime does not import untrusted paths, install plugins, or load remote executable code.
- **Explicit MCP tool registry:** MCP exposes only the injected canonical `ToolRegistry`; discovery is deterministic and unknown names fail closed.
- **Sanitized tool and readiness errors:** tool, MCP, and readiness failures expose stable operational messages without secrets, stack traces, or sensitive paths.
- **Transactional rollback:** persistence failures and multi-file development failures roll back changes, preventing partial records or partial task output.
- **Mocked external calls in tests:** GitHub, LLM, and other external interactions are injected and mocked so tests remain deterministic and do not transmit project data.

These controls are application-level safeguards. The project does not provide built-in authentication, authorization, cloud deployment, Kubernetes orchestration, distributed execution, or a process/VM sandbox. Deployments requiring those capabilities must add them at the appropriate boundary.

## Roadmap status

The complete V1–V7 roadmap is implemented:

- **V1 — Complete:** foundational multi-agent analysis and GitHub repository discovery.
- **V2 — Complete:** provider abstractions, robust repository/tree handling, configuration, and defensive validation.
- **V3 — Complete:** asynchronous SQLAlchemy persistence, Alembic migrations, PostgreSQL support, and analysis history API.
- **V4 — Complete:** local dashboard and same-origin static assets.
- **V5 — Complete:** explicit Skills/Tools runtime, deterministic registries, safe executor, and controlled autonomous workflows.
- **V6 — Complete:** official MCP SDK v2 `MCPServer`/`Client` integration over the canonical registry.
- **V7 — Complete:** production configuration, Dockerfile, Docker Compose migration startup, health/readiness endpoints, GitHub Actions CI, security hardening, and the complete deterministic test suite.

Further transport exposure for MCP, larger-repository traversal, authentication, cloud deployment, Kubernetes, and distributed execution are not implemented features of this project.