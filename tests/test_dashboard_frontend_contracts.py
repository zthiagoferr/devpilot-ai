"""Regression contracts for the dashboard frontend fixes.

The dashboard is a static bundle (HTML + CSS + JavaScript) served by FastAPI and
published to GitHub Pages, and the project has no JavaScript test runner. These
tests therefore pin, against the assets the application actually serves, the
concrete regressions reported for the dashboard:

* the "Colar código" / "Repositório GitHub" tabs could not be switched and did
  not follow the ARIA tabs pattern (mouse *and* keyboard);
* the analyzed source code returned by ``GET /analyses/{id}`` was never painted
  because the renderer looked for selectors the markup does not define;
* the recent-activity list collapsed into the narrow timeline column, the detail
  fields and the issue list had no styling, and the history table lost its
  columns under compression.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class _TagCollector(HTMLParser):
    """Collect every start tag with its attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag.lower(), {name: value for name, value in attrs}))


def _dashboard_html() -> str:
    response = client.get("/dashboard")
    assert response.status_code == 200
    return response.text


def _dashboard_asset(suffix: str) -> str:
    urls = re.findall(
        rf"""(?:href|src)\s*=\s*["']([^"']+{re.escape(suffix)})["']""",
        _dashboard_html(),
        flags=re.IGNORECASE,
    )
    assert urls, f"the dashboard must reference a local {suffix} asset"
    response = client.get(urls[0])
    assert response.status_code == 200
    return response.text


def _javascript() -> str:
    return _dashboard_asset(".js")


def _css() -> str:
    return _dashboard_asset(".css")


def _tags(html: str, tag: str) -> list[dict[str, str | None]]:
    parser = _TagCollector()
    parser.feed(html)
    return [attrs for name, attrs in parser.tags if name == tag]


def _compact(source: str) -> str:
    """Collapse whitespace so substring checks survive re-formatting."""
    return re.sub(r"\s+", " ", source)


def _css_declarations(css: str, selector: str) -> list[str]:
    """Return the declaration blocks of every rule matching ``selector``."""
    declarations: list[str] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        # The selector text may include a preceding ``@media`` header line.
        selector_text = match.group(1).split("\n")[-1]
        selectors = {part.strip() for part in selector_text.split(",")}
        if selector in selectors:
            declarations.append(match.group(2))
    return declarations


def test_dashboard_source_tabs_follow_the_aria_tabs_pattern() -> None:
    html = _dashboard_html()

    source_tabs = [
        tab for tab in _tags(html, "button") if tab.get("data-source-tab")
    ]
    assert {tab["data-source-tab"] for tab in source_tabs} == {"code", "github"}

    panels = {
        panel.get("id"): panel
        for panel in _tags(html, "div")
        if panel.get("role") == "tabpanel"
    }
    assert set(panels) >= {"source-code-panel", "source-github-panel"}

    selected = [tab for tab in source_tabs if tab.get("aria-selected") == "true"]
    assert len(selected) == 1, "exactly one source tab must be selected"
    active = selected[0]

    for tab in source_tabs:
        assert tab.get("role") == "tab"
        assert tab.get("aria-controls") in panels
        assert tab.get("tabindex") in {"0", "-1"}

    # Roving tabindex: only the selected tab is part of the tab sequence.
    assert active["tabindex"] == "0"
    for tab in source_tabs:
        if tab is active:
            continue
        assert tab["aria-selected"] == "false"
        assert tab["tabindex"] == "-1"

    # Every panel is labelled by its owning tab and only the selected tab's
    # panel is visible.
    for panel_id, panel in panels.items():
        owning_tab = next(
            tab for tab in source_tabs if tab["aria-controls"] == panel_id
        )
        assert panel.get("aria-labelledby") == owning_tab["id"]
        assert ("hidden" in panel) is (panel_id != active["aria-controls"])


def test_dashboard_javascript_switches_source_tabs_with_mouse_and_keyboard() -> None:
    script = _compact(_javascript())

    assert "activateSourceTab" in script
    assert "aria-selected" in script
    assert 'setAttribute("tabindex"' in script

    click_start = script.index('addEventListener("click"')
    keydown_start = script.index('addEventListener("keydown"', click_start)
    click_handler = script[click_start:keydown_start]
    assert "data-source-tab" in click_handler
    assert "activateSourceTab" in click_handler

    keyboard_handler = script[script.index("function handleSourceTabKeydown"):]
    for key in ('"ArrowRight"', '"ArrowLeft"', '"Home"', '"End"'):
        assert key in keyboard_handler
    assert "activateSourceTab" in keyboard_handler
    assert 'addEventListener("keydown", handleSourceTabKeydown)' in script


def test_dashboard_detail_renders_the_source_code_served_by_the_api() -> None:
    html = _dashboard_html()
    script = _compact(_javascript())

    # The markup keeps a dedicated element for the analyzed source.
    assert re.search(r"<code[^>]*\bdata-source-code\b", html)

    # The renderer must read the persisted field and resolve the element that
    # the markup actually defines, falling back to the detail section.
    assert "item.source_code" in script
    assert "code[data-source-code]" in script
    assert ".source-output" in script
    assert "|| section, item.source_code" in script


def test_dashboard_detail_labels_and_issue_list_are_styled() -> None:
    css = _css()

    field_meta = " ".join(_css_declarations(css, ".field-meta"))
    assert "text-transform: uppercase" in field_meta
    assert "font-size: 10px" in field_meta

    strong_value = " ".join(_css_declarations(css, ".detail-field > strong"))
    assert "overflow-wrap: anywhere" in strong_value

    assert _css_declarations(css, ".issue-list")
    assert _css_declarations(css, ".issue-list__item")
    assert _css_declarations(css, ".empty-state__text")


def test_dashboard_recent_list_rows_span_the_full_panel_width() -> None:
    declarations = _css_declarations(_css(), ".activity-item__button")

    assert declarations, "expected a .activity-item__button rule"
    combined = " ".join(declarations)
    assert "display: flex" in combined
    assert "grid-column: 1 / -1" in combined
    assert "width: 100%" in combined

    assert _css_declarations(_css(), ".activity-main")
    assert _css_declarations(_css(), ".activity-status")


def test_dashboard_history_table_keeps_readable_columns() -> None:
    css = _css()

    table_declarations = " ".join(_css_declarations(css, "table"))
    assert "min-width" in table_declarations

    table_wrap = " ".join(_css_declarations(css, ".table-wrap"))
    assert "overflow-x: auto" in table_wrap


def test_dashboard_text_buttons_are_not_rendered_with_default_chrome() -> None:
    declarations = _css_declarations(_css(), ".text-button")

    assert declarations, "expected a .text-button rule"
    combined = " ".join(declarations)
    assert "border: 0" in combined
    assert "background: transparent" in combined

    # The mobile step indicator must not wrap between its number and label.
    step_indicator = " ".join(_css_declarations(_css(), ".step-indicator"))
    assert "white-space: nowrap" in step_indicator


def test_dashboard_javascript_data_hooks_exist_in_the_markup() -> None:
    """Every critical hook the dashboard queries must exist in the markup.

    This is the class of defect behind the "source code is never shown" bug: the
    renderer queried an attribute no element defines. The check is bidirectional
    so an unreferenced (dead) platform field, such as the analysis origin, is
    also caught.
    """
    html = _dashboard_html()
    script = _compact(_javascript())
    required_hooks = (
        "data-source-code",
        "data-source-type",
        "data-source-tab",
        "data-source-panel",
        "data-analysis-form",
        "data-github-form",
        "data-load-repository",
        "data-submit-github",
        "data-repository-file",
        "data-recent-list",
        "data-recent-empty",
        "data-history-list",
        "data-history-table-wrap",
        "data-history-empty",
        "data-history-error",
        "data-history-loading",
        "data-detail-section",
        "data-detail-name",
        "data-detail-meta",
        "data-result-score",
        "data-result-status",
        "data-result-summary",
        "data-created-at",
        "data-analysis-id",
        "data-issues-list",
        "data-connection-dot",
        "data-connection-status",
        "data-stat",
        "data-view-section",
    )

    # ``data-recent-empty`` is composed at runtime by ``showState`` from the
    # state name, so only its presence in the markup is asserted.
    javascript_hooks = tuple(
        hook for hook in required_hooks if hook != "data-recent-empty"
    )

    assert [hook for hook in required_hooks if hook not in html] == []
    assert [hook for hook in javascript_hooks if hook not in script] == []
