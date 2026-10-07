import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class _DashboardHTMLParser(HTMLParser):
    """Collect the small amount of structure needed by dashboard contracts."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.tags.append(tag)
        if tag in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.text.append(data)


def _asset_urls(html: str, suffix: str) -> list[str]:
    urls = re.findall(
        r"(?:href|src)\s*=\s*[\"']([^\"']+)[\"']",
        html,
        flags=re.IGNORECASE,
    )
    return [
        url
        for url in urls
        if urlsplit(url).path.lower().endswith(suffix)
    ]


def test_dashboard_renders_semantic_content() -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    parser = _DashboardHTMLParser()
    parser.feed(response.text)
    visible_text = " ".join(" ".join(parser.text).split()).lower()

    assert "devpilot" in visible_text
    assert "dashboard" in visible_text
    assert "analysis" in visible_text
    assert "developer" in visible_text
    assert "h1" in parser.tags
    assert "form" in parser.tags
    assert "button" in parser.tags
    assert "textarea" in parser.tags


def test_dashboard_does_not_render_secrets_or_configuration_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets = {
        "LLM_API_KEY": "dashboard-test-llm-secret-7f3e",
        "DATABASE_URL": "postgresql://dashboard-test-secret@localhost/private",
        "GITHUB_TOKEN": "dashboard-test-github-secret-9a2b",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)

    response = client.get("/dashboard")

    assert response.status_code == 200
    body = response.text

    for value in secrets.values():
        assert value not in body

    for name in (
        "LLM_API_KEY",
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "SECRET_KEY",
    ):
        assert name not in body

    assert "postgresql://" not in body
    assert "postgres://" not in body
    assert not re.search(r"\bsk-[A-Za-z0-9_-]{8,}\b", body)


def test_dashboard_uses_only_local_css_and_javascript_assets() -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    css_urls = _asset_urls(response.text, ".css")
    javascript_urls = _asset_urls(response.text, ".js")
    assert css_urls
    assert javascript_urls

    for asset_url in [*css_urls, *javascript_urls]:
        parsed = urlsplit(asset_url)
        assert parsed.scheme == ""
        assert parsed.netloc == ""
        assert parsed.path.startswith("/")


def test_dashboard_local_css_assets_are_served_by_fastapi() -> None:
    dashboard = client.get("/dashboard")

    for asset_url in _asset_urls(dashboard.text, ".css"):
        response = client.get(asset_url)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/css")
        assert response.text.strip()


def test_dashboard_local_javascript_assets_are_served_by_fastapi() -> None:
    dashboard = client.get("/dashboard")

    for asset_url in _asset_urls(dashboard.text, ".js"):
        response = client.get(asset_url)
        assert response.status_code == 200
        content_type = response.headers["content-type"].lower()
        assert "javascript" in content_type or "ecmascript" in content_type
        assert response.text.strip()
