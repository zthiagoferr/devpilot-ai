# devpilot-ai

English | [Português](README.pt-BR.md)

🧠 Multi-agent AI platform for intelligent software project analysis.

## Overview

DevPilot discovers a GitHub repository, builds an analysis context, and coordinates specialized agents to produce a structured result. Version 3 adds persistent analysis history through an asynchronous SQLAlchemy persistence layer and HTTP endpoints for creating and retrieving analyses.

Version 4 adds a browser dashboard at [`/dashboard`](http://localhost:8000/dashboard). The dashboard provides a local user interface for submitting analysis input, viewing results, browsing persisted analysis history, and using the repository-discovery workflow. It uses the same application services and HTTP API as the programmatic clients; it does not replace the API or add capabilities that are not supported by the backend.

Version 5 adds a controlled skills-and-tools runtime. Tools expose explicitly registered project capabilities, skills group approved tools for agent workflows, and a `ToolExecutor` validates registry lookups and returns structured, secret-safe results. V5 does not provide arbitrary command execution, dynamic plugin loading, or a general-purpose code execution environment.

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

## V4 Dashboard

### Local startup and use

Install the project and development dependencies as described in [Installation and setup](#installation-and-setup), configure the required settings, and start the ASGI application:

```bash
uvicorn app.main:app --reload
```

Open [http://localhost:8000/dashboard](http://localhost:8000/dashboard) in a browser. The API documentation remains available at [http://localhost:8000/docs](http://localhost:8000/docs).

For a useful local setup, SQLite avoids requiring a separate database server:

```bash
export DATABASE_URL="sqlite+aiosqlite:///./devpilot.db"
alembic upgrade head
uvicorn app.main:app --reload
```

The dashboard is served by the running FastAPI application. Keep that process running while using the page; changing frontend files and restarting or reloading the development server may be necessary when adding or editing local assets.

### Workflows exposed by the UI

The dashboard exposes the application workflows that are supported by the current backend:

- **Analysis:** submit the project information and source or analysis input through the dashboard, then view the returned multi-agent analysis and report.
- **History:** view previously persisted analyses and open an individual record when the persistence configuration and API are available. History is backed by the V3 `/analyses` endpoints, so it is not a browser-only cache.
- **GitHub:** use the repository-discovery input to request metadata and the recursive file tree for a repository through the configured GitHub provider. The provider's authentication, default-branch, endpoint, malformed-response, and tree-size behavior still applies.

The dashboard does not imply support for downloading arbitrary repository contents, inspecting other branches or historical revisions, user authentication, or features not implemented by the API. Use `/docs` and the source code as the authoritative contract for request fields, response shapes, limits, and errors.

### Dashboard architecture

The dashboard is a thin presentation layer over the existing application boundaries:

- FastAPI serves the `/dashboard` HTML document and local static CSS and JavaScript assets.
- Browser code manages form interaction, requests, loading and error states, and rendering of API responses.
- API routes validate requests and delegate analysis, GitHub discovery, and history operations to the corresponding services.
- The agent orchestration layer coordinates the specialized analyzers.
- The persistence layer stores and retrieves completed analyses when configured.
- The GitHub provider performs external repository requests behind its provider interface.

The browser is not a substitute for the service layer and should not be treated as a trusted execution environment. Business rules, validation, provider access, persistence, and secret handling remain server-side.

### Local static assets

The dashboard references CSS and JavaScript files served from this application rather than loading frontend assets from a CDN or another origin. This keeps the default development page usable without external asset hosts and makes the asset behavior testable in the FastAPI test client.

When changing dashboard assets, preserve same-origin, root-relative URLs and ensure that FastAPI continues to serve them with the appropriate CSS or JavaScript content type. Do not put API keys, database URLs, GitHub tokens, or other deployment configuration into HTML, CSS, JavaScript, data attributes, or browser storage.

### Accessibility and responsiveness

The dashboard is intended to remain usable across desktop and narrow viewport sizes. Its markup should retain semantic headings, labels, forms, buttons, and text areas; controls should be keyboard reachable and have clear visible focus states; status, loading, error, and result messages should be understandable without relying only on color. Responsive layout changes should not hide required controls or force horizontal scrolling on ordinary mobile widths.

These are UI requirements rather than a claim of complete accessibility certification. Verify behavior with keyboard navigation, a screen reader where practical, zoom or larger text, and a narrow viewport when making dashboard changes.

### Dashboard security boundaries

The dashboard is a client of the backend, not a place to expose configuration. Server-side environment variables and settings must never be rendered into the page or returned solely for display. In particular, `LLM_API_KEY`, `DATABASE_URL`, `GITHUB_TOKEN`, and equivalent secrets must remain on the server.

The browser can submit data to the endpoints made available by the application, so deployments should apply their own network controls, authentication, rate limiting, and HTTPS policy when those are required. The dashboard itself does not claim to provide user authentication or authorization. Treat submitted source code, repository identifiers, and analysis results as potentially sensitive, and avoid logging them unnecessarily.

## V5 Skills and Tools

V5 exposes capabilities through explicit contracts rather than allowing agents to call arbitrary Python or operating-system functionality. The source tree and generated API documentation remain authoritative; the following describes the intended runtime boundaries without claiming capabilities that are not implemented.

### Tool contract

A tool is a named, registered capability with a stable metadata contract and an asynchronous execution method. A tool should provide:

- A unique, non-empty `name`.
- A human-readable `description` that does not contain credentials or other sensitive runtime data.
- A JSON-serializable `input_schema` describing accepted arguments, including required fields and whether additional properties are allowed.
- An asynchronous `execute(**kwargs)` operation returning a structured result, normally containing a `status` such as `completed` or `error`.
- Safe failure behavior: errors should identify the failed operation without returning secrets, file contents that were not requested, credentials, stack traces, or sensitive absolute paths.

The schema is a validation and discovery contract, not permission to perform operations outside the tool's implementation. Tools must enforce their own project-root, path, timeout, and output-size boundaries.

The built-in project filesystem capabilities are deliberately narrow: `list_files` lists eligible project files, `read_file` reads an allowed project-relative file, and `write_file` writes an allowed project-relative file. The test capability `run_tests` is a bounded project test operation where enabled by the application. Protected files and directories, path traversal, symlinks escaping the project root, and secret-bearing error details must be rejected. The exact available set depends on the configured application and source tree.

### Skill contract

A skill is a named, descriptive grouping of approved tools for a particular agent workflow. A skill has a unique `name`, a `description`, and an explicit list of tool names. Skill registration does not grant tools that are not present in the tool registry and does not bypass tool validation or execution limits. Skills are orchestration metadata, not dynamically loaded code or an authorization mechanism by themselves.

### Registries and deterministic discovery

`ToolRegistry` and `SkillRegistry` are separate, instance-scoped registries. Registration rejects invalid objects and duplicate names. Lookup of an unknown name fails rather than silently creating or importing a capability. Discovery/listing returns registered entries in deterministic name order, and public metadata must be JSON serializable so it can be inspected by agents and tests without exposing implementation state.

Discovery is explicit and deterministic: the application constructs the approved tools and skills, registers them, and exposes their metadata. V5 does not scan arbitrary directories, execute discovered files, trust user-provided import paths, install plugins, load remote code, or use untrusted dynamic imports. A deployment may inject a different provider, registry, or tool implementation through normal application configuration and dependency injection, but that remains controlled application code reviewed by the deployment.

### ToolExecutor

`ToolExecutor` is the execution boundary between orchestration and tools. It resolves a tool by its registered name, validates or delegates validation of the input contract, invokes the asynchronous operation, and normalizes failures into structured results. Missing tools, invalid arguments, timeouts, and tool exceptions must fail closed. Executor failures must not echo arbitrary arguments or include secret values, stack traces, request headers, environment variables, or secret-bearing discovery metadata.

The executor is not a shell, Python evaluator, sandbox escape hatch, or permission escalation layer. Registering a tool is the point at which its capability is approved; an agent cannot turn a tool name or schema into an arbitrary command.

### Dependency injection and runtime isolation

Services receive their collaborators explicitly where supported: providers, HTTP clients, persistence sessions, project roots, registries, and executors can be supplied by the application composition layer and replaced in tests. This keeps network access, storage, and tool execution behind interfaces and avoids hidden global registries or ambient credentials.

Each runtime should use an isolated project workspace and an isolated registry instance. Filesystem tools must resolve paths beneath the configured project root, reject protected locations and escaping symlinks, and avoid exposing host files. Test execution, when enabled, is bounded by the tool's timeout and project scope. Isolation here means application-level workspace and capability boundaries; V5 does not claim to provide a container, VM, process sandbox, or comprehensive OS security boundary.

### Approved capabilities and explicit security boundaries

The approved default project capabilities are limited to the tools registered by the application, such as safe project file listing, controlled project-file reads and writes, repository/provider operations, and the bounded test tool where configured. They do not include a generic `shell`, `run_shell`, `execute_command`, arbitrary subprocess API, unrestricted network client, or arbitrary code evaluator.

In particular, V5 must not:

- Execute arbitrary shell commands or accept a command string as a general-purpose capability.
- Import untrusted modules or execute user-supplied dynamic import paths.
- Install plugins or packages as part of discovery or execution.
- Load executable code, tools, or skills from remote URLs, repositories, or model output.
- Put API keys, tokens, database URLs, authorization headers, environment snapshots, or secret-bearing exception/discovery metadata into tool results, registry metadata, logs, or dashboard responses.

These are security boundaries, not promises that every deployment is secure by default. Operators should still apply authentication, authorization, network egress controls, resource limits, filesystem permissions, dependency review, and secret-management practices appropriate to their environment.

### V5 usage architecture

A typical supported flow is:

1. The application composition layer creates approved provider, filesystem, persistence, tool, and skill dependencies.
2. The tool and skill registries register validated instances and expose deterministic, non-secret metadata.
3. An agent receives the relevant skill contract and selects a declared tool by name.
4. `ToolExecutor` resolves the name, validates inputs, applies the tool's boundaries, and awaits execution.
5. The tool returns a structured result; the executor returns a normalized safe success or failure result to the agent.
6. The analysis workflow combines the result with other agent output and returns it through the existing service/API or dashboard layers.

The browser and model are untrusted callers of this flow. Authorization, validation, capability selection, isolation, and secret handling remain server-side.

## Architecture

The project is organized around clear application boundaries:

- **API layer** — HTTP routes for analysis execution, analysis history, and the dashboard entry point.
- **Core configuration** — validated settings and environment-variable integration.
- **Agents** — specialized asynchronous analyzers coordinated by the analysis workflow.
- **Tools** — reusable, explicitly registered capabilities such as repository discovery, safe project filesystem operations, and bounded test execution.
- **Skills** — named groupings of approved tools used by agent workflows.
- **Tool runtime** — isolated registries, deterministic discovery, dependency injection, and `ToolExecutor` execution boundaries.
- **GitHub providers** — an interface and an asynchronous `httpx` implementation for repository access.
- **Persistence** — SQLAlchemy models, asynchronous database configuration, and the analysis repository.
- **Migrations** — Alembic revisions for database schema changes.
- **Dashboard** — a browser-facing HTML interface with local static assets over the existing API and services.
- **Tests** — unit and asynchronous integration coverage, including an SQLite/`aiosqlite` persistence fixture and dashboard asset/HTML checks.

A typical repository layout is:

```text
app/
  agents/
  api/
  core/
  persistence/
  providers/
  skills/
  tools/
  static/
tests/
alembic/
README.md
README.pt-BR.md
```

The names and boundaries above reflect the current architecture; consult the source tree for the definitive module list.

## Installation and setup

Create and activate a virtual environment, then install the project and development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
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

Dashboard tests request `/dashboard`, verify semantic content, confirm that configuration values and secrets are not rendered, and check that referenced CSS and JavaScript assets are local and served by FastAPI. When changing dashboard markup or assets, run the complete suite and manually check the workflows at `/dashboard` in a browser.

Persistence tests use an in-memory SQLite database with `aiosqlite` when the asynchronous SQLAlchemy dependencies are available. The HTTP GitHub provider accepts an injected `httpx.AsyncClient`, allowing tests and callers to provide a custom transport without making real network requests. V5 runtime tests should also verify duplicate rejection, deterministic registry ordering, isolated registry instances, safe executor failures, protected filesystem paths, and absence of arbitrary shell capabilities.

## Status and roadmap

- **V1/V2:** GitHub repository discovery, provider abstraction, default-branch handling, recursive tree discovery, authentication, configurable API endpoints, and defensive response validation are available.
- **V3:** Persistent analysis history, asynchronous SQLAlchemy persistence, Alembic migrations, PostgreSQL/`asyncpg` production support, SQLite/`aiosqlite` test support, and the analysis history endpoints are available.
- **V4:** The local `/dashboard` interface, same-origin static assets, and UI access to the supported analysis, history, and GitHub discovery workflows are available.
- **V5:** Explicit tool and skill contracts, isolated registries, deterministic metadata discovery, dependency-injected capabilities, and `ToolExecutor` safe execution boundaries are available where implemented by the current source tree. V5 does not provide arbitrary shell execution, untrusted dynamic imports, plugin installation, remote code loading, or a process/container sandbox.
- **Future work:** Large-repository discovery improvements, including pagination or alternate tree traversal, remain roadmap items. The current provider intentionally rejects truncated GitHub tree responses and does not inspect additional branches or historical revisions.

## Security

Never commit tokens, passwords, API keys, or personal credentials to this repository. Supply secrets through environment variables, deployment secrets, or the application's external configuration mechanism. Keep local secret files out of version control, rotate any exposed credential, and avoid printing provider objects, request headers, or exception details that could disclose secrets.

The V5 runtime is capability-based at the application level: only explicitly approved and registered tools can be selected, and registries do not dynamically load arbitrary code. It does not permit arbitrary shell execution, untrusted dynamic imports, plugin installation, remote code loading, or secret-bearing error and discovery metadata. These boundaries do not replace deployment-level authentication, authorization, network controls, resource limits, filesystem permissions, dependency review, or process/container isolation where those are required.

The dashboard follows the same boundary: it may display server responses needed for an analysis workflow, but it must not expose server configuration or credentials. Deployments that need access control must provide it at the appropriate network or application boundary; the current dashboard documentation does not claim built-in authentication.
