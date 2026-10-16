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
  columns under compression;
* "Carregar arquivos do repositório" produced no visible feedback on any path
  (loading, success, empty repository, HTTP error, network error) because every
  message was written to the ``visually-hidden`` live region only, and a failed
  request left the previously loaded file list selectable.
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


def _without_comments(source: str) -> str:
    """Drop ``//`` line comments so contracts only match executable code.

    Applied to the raw source, before :func:`_compact` collapses the newlines
    that delimit a line comment; otherwise the strip would swallow the code
    that follows the comment on the same logical line.
    """
    return re.sub(r"//[^\n]*", "", source)


def _function(script: str, name: str) -> str:
    """Return the source of the ``name`` function up to the next declaration."""
    start = script.index(f"function {name}(")
    match = re.search(r"function [A-Za-z_$][\w$]*\(", script[start + 1 :])
    return script[start:] if match is None else script[start : start + 1 + match.start()]


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
        "data-analysis-status",
        "data-error-message",
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


def test_dashboard_repository_load_button_is_wired_to_the_loader() -> None:
    """Clicking "Carregar arquivos do repositório" must call the loader."""
    script = _compact(_javascript())

    wiring = _function(script, "init")
    loader = wiring[
        wiring.index("var loader = one(["): wiring.index("var fileSelect = one([")
    ]
    assert "data-load-repository" in loader
    assert 'addEventListener("click"' in loader
    assert "loadRepository(github)" in loader
    assert "event.preventDefault()" in loader


def test_dashboard_feedback_is_mirrored_into_a_visible_status_node() -> None:
    """The live region is screen-reader only, so feedback needs a visible twin.

    The reported bug ("no files and no feedback") happened because
    ``announce`` wrote exclusively to ``#announcements``, which is
    ``visually-hidden``: assistive technology heard the outcome while a sighted
    user saw nothing.
    """
    html = _dashboard_html()
    script = _compact(_javascript())

    announcements = [tag for tag in _tags(html, "div") if tag.get("id") == "announcements"]
    assert len(announcements) == 1
    assert "visually-hidden" in (announcements[0].get("class") or "")

    visible = [tag for tag in _tags(html, "div") if "data-analysis-status" in tag]
    assert len(visible) == 1, "exactly one visible status line must receive the feedback"
    status = visible[0]
    assert "visually-hidden" not in (status.get("class") or "")
    assert "hidden" in status, "the status line starts hidden and is revealed on demand"

    body = _function(script, "announce")
    assert "[data-analysis-status]" in body
    assert 'target.hidden = value === ""' in body
    assert "target.dataset.status" in body


def test_dashboard_announcements_carry_a_visible_tone() -> None:
    """Error/success/info tones must have a visible treatment."""
    css = _css()

    error = " ".join(_css_declarations(css, '.inline-status[data-status="error"]'))
    success = " ".join(_css_declarations(css, '.inline-status[data-status="success"]'))
    assert "--red" in error
    assert "--mint" in success

    script = _compact(_javascript())
    assert '"success"' in script
    assert 'error ? "error" : "info"' in script


def test_dashboard_request_surfaces_api_details_and_translates_network_failures() -> None:
    """Non-OK responses keep their API detail; transport failures are translated."""
    body = _function(_compact(_javascript()), "request")

    # Non-OK responses: ``detail`` first, then ``message``, then the status code.
    assert "body.detail" in body
    assert "body.message" in body
    assert "response.status" in body

    # ``fetch`` rejects with a ``TypeError`` whose message ("Failed to fetch") is
    # useless to the user. Only the transport rejection handler may translate it,
    # so API errors keep the message thrown by the fulfilled handler.
    assert "Não foi possível acessar a API do DevPilot" in body
    assert "}, function () {" in body
    assert "if (error && error.message) throw error;" not in body


def test_dashboard_repository_success_fills_and_enables_the_file_select() -> None:
    body = _function(_compact(_javascript()), "loadRepository")

    assert "state.repositoryFiles" in body
    assert "select.disabled = empty" in body
    assert 'announce(message, false, "success")' in body
    assert '"Arquivos do repositório carregados ("' in body
    assert "submit.disabled = true" in body


def test_dashboard_repository_empty_result_is_announced() -> None:
    """A valid repository without Python files is a 200 with ``files: []``."""
    body = _function(_compact(_javascript()), "loadRepository")

    assert "payload.message" in body
    assert "Nenhum arquivo Python elegível foi encontrado neste repositório." in body
    assert "Nenhum arquivo Python encontrado neste repositório" in body


def test_dashboard_failed_repository_load_clears_stale_files() -> None:
    """A failed load must not leave a file list belonging to another reference."""
    body = _function(_compact(_javascript()), "loadRepository")

    assert "clearRepositoryFiles(form)" in body
    rejection = body[body.index(".catch(function (error)") :]
    assert "clearRepositoryFiles(form)" in rejection
    assert "id === sequence.repository" in rejection

    reset = _function(_compact(_javascript()), "clearRepositoryFiles")
    assert "state.repositoryFiles = []" in reset
    assert "select.disabled = true" in reset
    assert "submit.disabled = true" in reset


def test_dashboard_analysis_failure_publishes_the_reason_visibly() -> None:
    """The visible error block must show the reason, not only the generic text."""
    body = _function(_compact(_javascript()), "submitForm")

    assert "[data-error-message]" in body
    assert "detail.textContent = error.message" in body


# ---------------------------------------------------------------------------
# Authentication (Firebase)
# ---------------------------------------------------------------------------

AUTH_HOOKS = (
    "data-auth-dialog",
    "data-auth-form",
    "data-auth-action",
    "data-auth-email",
    "data-auth-password",
    "data-auth-message",
    "data-auth-loading",
    "data-auth-account",
    "data-auth-when",
    "data-auth-user",
    "data-auth-hint",
    "data-auth-title",
    "data-auth-lead",
    "data-auth-verify",
    "data-auth-history-prompt",
    "data-auth-submit",
)


def test_dashboard_auth_hooks_exist_in_the_markup_and_in_the_script() -> None:
    """The same bidirectional contract used for the analysis hooks.

    Every ``data-auth-*`` hook the script queries must exist in the markup (and
    vice versa), so the sign-in surface cannot silently drift out of sync.
    """
    html = _dashboard_html()
    script = _compact(_javascript())

    assert [hook for hook in AUTH_HOOKS if hook not in html] == []
    assert [hook for hook in AUTH_HOOKS if hook not in script] == []


def test_dashboard_auth_dialog_offers_login_register_reset_and_github() -> None:
    html = _dashboard_html()

    dialogs = [tag for tag in _tags(html, "dialog") if "data-auth-dialog" in tag]
    assert len(dialogs) == 1, "exactly one auth dialog must exist"
    assert dialogs[0].get("aria-labelledby") == "auth-title"

    forms = {
        form.get("data-auth-form")
        for form in _tags(html, "form")
        if form.get("data-auth-form")
    }
    assert forms == {"login", "register", "reset"}

    actions = {
        button.get("data-auth-action")
        for button in _tags(html, "button")
        if button.get("data-auth-action")
    }
    assert {
        "open-login",
        "open-register",
        "open-reset",
        "close",
        "logout",
        "github",
        "verify-email",
    } <= actions

    # The password inputs must never be rendered as plain text.
    password_inputs = [
        tag
        for tag in _tags(html, "input")
        if "data-auth-password" in tag
    ]
    assert password_inputs
    assert {tag.get("type") for tag in password_inputs} == {"password"}


def test_dashboard_auth_messages_are_announced_by_the_shared_live_region() -> None:
    html = _dashboard_html()
    script = _compact(_javascript())

    messages = [tag for tag in _tags(html, "p") if "data-auth-message" in tag]
    assert len(messages) == 1
    assert messages[0].get("role") == "status"
    assert messages[0].get("aria-live") == "polite"

    assert [tag for tag in _tags(html, "div") if tag.get("id") == "announcements"]

    body = _function(script, "authMessage")
    assert "announce(value" in body
    assert "dataset.status" in body


def test_dashboard_authenticated_requests_send_the_bearer_token() -> None:
    script = _compact(_javascript())

    body = _function(script, "request")
    assert "Authorization" in body
    assert "Bearer " in body
    assert "authToken()" in body
    # A 401 must ask for a login instead of surfacing the raw API text.
    assert "response.status === 401" in body
    assert "openAuthDialog" in body

    token = _function(script, "authToken")
    assert "getIdToken" in token
    # A visitor never attaches a token.
    assert "isAuthenticated()" in token


def test_dashboard_restores_the_session_and_wires_every_auth_flow() -> None:
    script = _compact(_javascript())

    for symbol in (
        "onAuthStateChanged",
        "getIdToken",
        "signInWithEmailAndPassword",
        "createUserWithEmailAndPassword",
        "sendPasswordResetEmail",
        "sendEmailVerification",
        "GithubAuthProvider",
        "signInWithPopup",
        "signInWithRedirect",
        "signOut",
        "getAuth",
        "initializeApp",
    ):
        assert symbol in script, symbol


def test_dashboard_registers_the_auth_state_observer_with_the_sdk_signature() -> None:
    # ``startAuth`` documents the bug with an example call in a comment, so the
    # comments must be stripped before matching or the contract would assert
    # against the explanation instead of the call the code actually makes.
    start = _compact(_without_comments(_function(_javascript(), "startAuth")))
    match = re.search(r"([\w$.]+)\.onAuthStateChanged\(([^)]*)\)", start)
    assert match, "startAuth must register an auth state observer"

    receiver, arguments = match.group(1), match.group(2).strip()
    if receiver == "authApi":
        # Modular form: the instance comes first, the observer second.
        assert arguments == "auth, handleAuthState", arguments
    else:
        # Instance form: the observer is the only argument. Passing the auth
        # instance as the first argument (``auth.onAuthStateChanged(auth,
        # handleAuthState)``) makes the SDK run ``auth.next.bind(auth)`` and
        # throw synchronously, so the observer is never registered.
        assert arguments == "handleAuthState", arguments


def test_dashboard_translates_firebase_errors_to_portuguese() -> None:
    script = _compact(_javascript())

    body = _function(script, "authErrorMessage")
    assert "AUTH_ERRORS[code]" in body

    for code, message in (
        ("auth/invalid-credential", "E-mail ou senha inválidos."),
        ("auth/email-already-in-use", "já está cadastrado"),
        ("auth/weak-password", "muito fraca"),
        ("auth/too-many-requests", "Muitas tentativas"),
        ("auth/popup-closed-by-user", "foi fechada antes"),
        ("auth/network-request-failed", "Falha de rede"),
    ):
        assert code in script, code
        assert message in script, code


def test_dashboard_loads_the_auth_sdk_lazily_from_the_pinned_cdn() -> None:
    html = _dashboard_html()
    script = _compact(_javascript())

    assert "https://www.gstatic.com/firebasejs/" in script
    assert re.search(r'FIREBASE_SDK_VERSION = "\d+\.\d+\.\d+"', script)
    # Loaded through a dynamic import, never as an external <script src>.
    assert "import(FIREBASE_SDK_BASE" in script

    for tag in [*_tags(html, "script"), *_tags(html, "link")]:
        reference = tag.get("src") or tag.get("href") or ""
        assert not re.match(r"^(https?:)?//", reference), reference


def test_dashboard_without_firebase_configuration_keeps_the_visitor_flows() -> None:
    script = _compact(_javascript())

    # Placeholder (empty) public configuration: no Firebase project required.
    assert 'apiKey: ""' in script
    assert 'projectId: ""' in script

    configured = _function(script, "authConfigured")
    assert "FIREBASE_CONFIG.apiKey" in configured
    assert "FIREBASE_CONFIG.projectId" in configured

    start = _function(script, "startAuth")
    assert "authConfigured()" in start
    # The degraded path explains itself instead of throwing.
    assert "não está configurada neste ambiente" in start


def test_dashboard_history_prompt_is_shown_to_visitors() -> None:
    html = _dashboard_html()
    script = _compact(_javascript())

    prompt = [
        tag for tag in _tags(html, "div") if "data-auth-history-prompt" in tag
    ]
    assert len(prompt) == 1
    assert "hidden" in prompt[0], "the prompt starts hidden"

    body = _function(script, "loadHistory")
    assert "isAuthenticated()" in body
    assert "showHistoryPrompt(true)" in body

    # Visitors never fetch the owner-scoped history, so nothing leaks.
    sync = _function(script, "synchronizeStatuses")
    assert "isAuthenticated()" in sync
