# devpilot-ai

🧠 Multi-agent AI platform for intelligent software project analysis.

## GitHub repository discovery

DevPilot uses a provider abstraction for GitHub access. Application code depends on the provider interface rather than directly on a particular HTTP library, which keeps repository discovery replaceable and straightforward to test.

The included implementation uses [`httpx`](https://www.python-httpx.org/) and performs asynchronous GitHub REST API requests. It supports:

- Public repository discovery without credentials.
- Token-authenticated discovery for private repositories or higher GitHub API limits.
- Repository metadata lookup, including the repository's default branch.
- Recursive file-tree discovery from that default branch.
- Configurable GitHub-compatible API endpoints, including GitHub Enterprise Server installations.

A typical discovery flow is:

1. Request repository metadata from `/repos/{owner}/{repo}`.
2. Read the returned `default_branch` value.
3. Request `/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1`.
4. Return blob entries as repository files while ignoring directory (`tree`) entries.

The provider validates JSON responses and reports HTTP errors or malformed responses instead of silently returning incomplete data.

## Configuration

Configuration may be supplied by the application's settings system or environment variables. The supported GitHub settings are:

| Variable | Purpose | Default |
| --- | --- | --- |
| `GITHUB_TOKEN` | Optional personal access token or GitHub App token. If unset, requests are public and omit the `Authorization` header. | Unset |
| `GITHUB_API_BASE_URL` | GitHub REST API base URL override. Use this for GitHub Enterprise Server or a compatible API. | `https://api.github.com` |

The base URL may also be passed directly to the provider as `api_base_url` when constructing it. It is joined with API paths without changing the paths, so an override such as `https://github.example.test/api/v3` produces requests under `/api/v3/repos/...`.

Example environment configuration:

```bash
export GITHUB_TOKEN="your-token"
export GITHUB_API_BASE_URL="https://api.github.com"
```

For public repositories, leave `GITHUB_TOKEN` unset. When a token is configured, the HTTP implementation sends it in the request's authorization header; it does not include the token in URLs or normal error messages.

## Repository and tree limitations

The implementation follows the repository's reported `default_branch`; it does not assume that the branch is named `main` or `master`. A missing default branch is treated as an invalid metadata response.

File discovery uses GitHub's recursive Git tree endpoint. GitHub can set the response's `truncated` field to `true` when a tree is too large to return in one response. Because a truncated result is incomplete, DevPilot rejects it rather than presenting a partial project as complete. Large repositories may therefore need to be narrowed, split into smaller analyses, or handled by a future provider implementation with pagination or alternate traversal.

The current discovery behavior is intentionally limited to the returned tree entries: blob paths are exposed as files, while directory entries are omitted. It does not download file contents, enumerate every historical revision, or automatically traverse additional branches.

## Credentials and security

Never commit tokens, passwords, or personal credentials to this repository. Supply credentials through environment variables, deployment secrets, or the application's external configuration mechanism. Keep local secret files out of version control (for example, add `.env` files to `.gitignore`), rotate any credential that is exposed, and avoid printing provider objects, request headers, or exception details that could disclose secrets.

## Development

Install the project dependencies, configure any optional environment variables, and run the test suite with:

```bash
pytest
```

The HTTP provider accepts an injected `httpx.AsyncClient`, allowing tests and callers to provide a custom transport without making real network requests.