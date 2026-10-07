(function () {
  "use strict";

  var API_BASE = "";
  var requests = { history: 0, detail: 0, status: 0, analysis: 0 };
  var state = { history: [], selectedId: null };

  function byId(id) {
    return document.getElementById(id);
  }

  function first(selectors) {
    for (var i = 0; i < selectors.length; i += 1) {
      var element = document.querySelector(selectors[i]);
      if (element) return element;
    }
    return null;
  }

  function announce(message) {
    var element = first(["[data-announcement]", "#announcements", "#status-message"]);
    if (element) {
      element.textContent = message || "";
      element.setAttribute("role", "status");
      element.setAttribute("aria-live", "polite");
    }
  }

  function setState(name, value) {
    var element = first(["[data-state='" + name + "']", "[data-" + name + "]"]);
    if (element) element.hidden = !value;
  }

  function setBusy(element, busy) {
    if (!element) return;
    element.disabled = !!busy;
    element.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function endpoint(path) {
    return API_BASE.replace(/\/$/, "") + path;
  }

  function responseError(response, body) {
    var message = "Request failed (" + response.status + ")";
    if (body && typeof body === "object" && body.detail) {
      message = typeof body.detail === "string" ? body.detail : message;
    } else if (body && typeof body === "string" && body.trim()) {
      message = body.trim();
    }
    var error = new Error(message);
    error.status = response.status;
    return error;
  }

  async function request(path, options) {
    var response = await fetch(endpoint(path), Object.assign({
      headers: { "Accept": "application/json" }
    }, options || {}));
    var body = null;
    try { body = await response.json(); } catch (_) { body = null; }
    if (!response.ok) throw responseError(response, body);
    return body;
  }

  function jsonOptions(method, value) {
    return {
      method: method,
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(value)
    };
  }

  function text(value, fallback) {
    return value === null || value === undefined ? (fallback || "") : String(value);
  }

  function resultOf(record) {
    return record && (record.analysis_result || record.result) || {};
  }

  function renderIssues(container, issues) {
    if (!container) return;
    while (container.firstChild) container.removeChild(container.firstChild);
    if (!Array.isArray(issues) || issues.length === 0) {
      var none = document.createElement("p");
      none.textContent = "No issues found.";
      container.appendChild(none);
      return;
    }
    var list = document.createElement("ul");
    issues.forEach(function (issue) {
      var item = document.createElement("li");
      if (issue && typeof issue === "object") {
        item.textContent = text(issue.message || issue.description || issue.title, JSON.stringify(issue));
      } else {
        item.textContent = text(issue);
      }
      list.appendChild(item);
    });
    container.appendChild(list);
  }

  function renderRecord(record) {
    var result = resultOf(record);
    var container = first(["[data-analysis-detail]", "#analysis-detail"]);
    if (!container) return;
    container.hidden = false;
    var score = container.querySelector("[data-score]");
    var summary = container.querySelector("[data-summary]");
    var project = container.querySelector("[data-project-name]");
    var task = container.querySelector("[data-task]");
    var source = container.querySelector("[data-source-code]");
    var created = container.querySelector("[data-created-at]");
    if (score) score.textContent = text(result.score, "—");
    if (summary) summary.textContent = text(result.summary, "");
    if (project) project.textContent = text(record.project_name, "");
    if (task) task.textContent = text(record.task, "");
    if (source) source.textContent = text(record.source_code, "");
    if (created) created.textContent = text(record.created_at, "");
    renderIssues(container.querySelector("[data-issues]"), result.issues);
  }

  function renderHistory(records) {
    var container = first(["[data-analysis-history]", "#analysis-history"]);
    if (!container) return;
    while (container.firstChild) container.removeChild(container.firstChild);
    if (!Array.isArray(records) || records.length === 0) {
      var empty = document.createElement("p");
      empty.textContent = "No analyses yet.";
      container.appendChild(empty);
      return;
    }
    records.forEach(function (record) {
      var item = document.createElement("li");
      var button = document.createElement("button");
      button.type = "button";
      button.setAttribute("data-analysis-id", text(record.id));
      button.textContent = text(record.project_name, "Unnamed project") + " — " + text(record.created_at, "");
      item.appendChild(button);
      container.appendChild(item);
    });
  }

  async function loadHistory() {
    var requestId = ++requests.history;
    var container = first(["[data-analysis-history]", "#analysis-history"]);
    setState("loading", true);
    announce("Loading analysis history.");
    try {
      var records = await request("/analyses");
      if (requestId !== requests.history) return records;
      state.history = Array.isArray(records) ? records : [];
      renderHistory(state.history);
      setState("empty", state.history.length === 0);
      announce(state.history.length ? "Analysis history loaded." : "No analyses yet.");
      return state.history;
    } catch (error) {
      if (requestId !== requests.history) return;
      if (container) container.textContent = "Unable to load analysis history.";
      announce(error.message);
      setState("error", true);
      throw error;
    } finally {
      if (requestId === requests.history) setState("loading", false);
    }
  }

  async function loadDetail(id) {
    if (!id) return null;
    var requestId = ++requests.detail;
    state.selectedId = id;
    announce("Loading analysis details.");
    try {
      var record = await request("/analyses/" + encodeURIComponent(id));
      if (requestId !== requests.detail) return record;
      renderRecord(record);
      announce("Analysis details loaded.");
      return record;
    } catch (error) {
      if (requestId !== requests.detail) return;
      announce(error.message);
      throw error;
    }
  }

  async function createAnalysis(values) {
    var task = text(values.task, "code_analysis").trim();
    var projectName = text(values.project_name, "").trim();
    var sourceCode = text(values.source_code, "");
    if (!task || !projectName || !sourceCode.trim()) {
      throw new Error("Task, project name, and source code are required.");
    }
    return request("/analyses", jsonOptions("POST", {
      task: task,
      project_name: projectName,
      source_code: sourceCode
    }));
  }

  async function submit(form) {
    var button = form.querySelector("[type='submit']");
    var values = {};
    new FormData(form).forEach(function (value, key) { values[key] = value; });
    setBusy(button, true);
    setState("loading", true);
    announce("Running analysis.");
    var requestId = ++requests.analysis;
    try {
      var record = await createAnalysis(values);
      if (requestId !== requests.analysis) return;
      renderRecord(record);
      await loadHistory();
      announce("Analysis completed.");
    } catch (error) {
      if (requestId === requests.analysis) announce(error.message);
    } finally {
      if (requestId === requests.analysis) {
        setBusy(button, false);
        setState("loading", false);
      }
    }
  }

  async function loadStatus() {
    var requestId = ++requests.status;
    var element = first(["[data-status]", "#orchestrator-status"]);
    try {
      var status = await request("/agents/orchestrator");
      if (requestId !== requests.status) return status;
      if (element) element.textContent = text(status.status, "unknown");
      return status;
    } catch (error) {
      if (requestId === requests.status && element) element.textContent = "Unavailable";
      return null;
    }
  }

  function init(options) {
    options = options || {};
    API_BASE = text(options.apiBase, document.documentElement.getAttribute("data-api-base") || "");
    var form = first(["[data-analysis-form]", "#analysis-form"]);
    if (form) form.addEventListener("submit", function (event) { event.preventDefault(); submit(form); });
    var history = first(["[data-analysis-history]", "#analysis-history"]);
    if (history) history.addEventListener("click", function (event) {
      var target = event.target.closest ? event.target.closest("[data-analysis-id]") : null;
      if (target) loadDetail(target.getAttribute("data-analysis-id"));
    });
    loadHistory().catch(function () {});
    loadStatus();
  }

  window.DevPilotDashboard = {
    init: init,
    api: { request: request, createAnalysis: createAnalysis, loadHistory: loadHistory, loadDetail: loadDetail, loadStatus: loadStatus },
    renderHistory: renderHistory,
    renderRecord: renderRecord
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { init(); });
  else init();
}());