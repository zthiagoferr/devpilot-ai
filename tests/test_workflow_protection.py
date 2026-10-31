"""Policy tests for the deployment and CI workflows.

These tests read the YAML files and assert the *semantics* that protect the
published site and the repository quality gates. They intentionally look at the
concatenated ``run``/``uses`` text instead of exact formatting, so renaming a
step or reordering commands does not break the policy, while removing a gate
does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
PAGES = WORKFLOWS / "pages.yml"
CI = WORKFLOWS / "ci.yml"


def _load(path: Path) -> dict[str, Any]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return workflow


def _raw(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML resolves the YAML 1.1 keyword ``on`` to the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs") or []
    if isinstance(needs, str):
        return [needs]
    return list(needs)


def _job_text(job: dict[str, Any]) -> str:
    """Concatenate every ``run``/``uses`` value of a job's steps."""
    chunks: list[str] = []
    for step in job.get("steps") or []:
        for key in ("run", "uses"):
            value = step.get(key)
            if value:
                chunks.append(str(value))
    return "\n".join(chunks)


def test_pages_only_publishes_from_main() -> None:
    workflow = _load(PAGES)
    triggers = _triggers(workflow)

    push = triggers.get("push")
    assert isinstance(push, dict)
    assert push.get("branches") == ["main"]
    assert "workflow_dispatch" in triggers
    assert "preview-pages" not in triggers
    assert "preview-pages" not in _raw(PAGES)


def test_pages_has_the_verify_build_deploy_chain() -> None:
    jobs = _load(PAGES)["jobs"]

    assert {"verify", "build", "deploy"} <= set(jobs)
    assert "verify" in _needs(jobs["build"])
    assert {"verify", "build"} <= set(_needs(jobs["deploy"]))
    assert "refs/heads/main" in str(jobs["deploy"].get("if", ""))


def test_pages_verify_runs_the_full_quality_gate() -> None:
    verify = _job_text(_load(PAGES)["jobs"]["verify"])

    assert "python -m compileall -q app tests alembic" in verify
    assert "python -m pytest -p no:cacheprovider" in verify
    assert "npx tsc --noEmit -p tsconfig.app.json" in verify
    assert "npx tsc --noEmit -p tsconfig.spec.json" in verify
    assert "npx ng test --watch=false" in verify
    assert "npx ng build --configuration production" in verify


def test_pages_build_requires_a_public_api_url_and_validates_the_artifact() -> None:
    build = _job_text(_load(PAGES)["jobs"]["build"])

    assert "DEVPILOT_API_URL" in build
    assert "exit 1" in build
    assert "--base-href" in build
    assert "upload-pages-artifact" in build
    assert "index.html" in build
    assert "config.js" in build
    assert "Smoke em subpath" in build


def test_pages_deploy_uses_the_github_pages_environment() -> None:
    deploy = _load(PAGES)["jobs"]["deploy"]

    environment = deploy.get("environment")
    assert isinstance(environment, dict)
    assert environment.get("name") == "github-pages"


def test_pages_concurrency_never_cancels_a_running_deploy() -> None:
    concurrency = _load(PAGES).get("concurrency")

    assert isinstance(concurrency, dict)
    assert concurrency.get("group") == "pages"
    assert concurrency.get("cancel-in-progress") is False


def test_ci_runs_on_main_and_pull_requests() -> None:
    workflow = _load(CI)
    triggers = _triggers(workflow)

    push = triggers.get("push")
    assert isinstance(push, dict)
    assert push.get("branches") == ["main"]
    assert "pull_request" in triggers

    text = _job_text(workflow["jobs"]["test"]) + "\n" + _job_text(
        workflow["jobs"]["frontend"]
    )
    assert "python -m pytest" in text
    assert "npx tsc --noEmit -p tsconfig.app.json" in text
    assert "npx tsc --noEmit -p tsconfig.spec.json" in text
    assert "npx ng test --watch=false" in text
    assert "npx ng build --configuration production" in text


def test_workflows_do_not_chain_on_workflow_run_or_ignore_failures() -> None:
    for path in (PAGES, CI):
        raw = _raw(path)
        assert "workflow_run" not in raw
        assert "continue-on-error" not in raw
