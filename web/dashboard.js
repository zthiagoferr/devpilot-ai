(function () {
  "use strict";

  var API_BASE = "";
  var STATIC = false;
  var started = false;
  var statusTimer = null;
  var state = { history: [], selectedId: null, repositoryFiles: [], view: "overview" };
  var sequence = { history: 0, detail: 0, repository: 0 };
  var CONTRACT = {
    history: { method: "GET", path: "/analyses" },
    detail: { method: "GET", path: "/analyses/{id}" },
    create: { method: "POST", path: "/analyses" },
    repository: { method: "POST", path: "/repositories/load" },
    status: { method: "GET", path: "/agents/orchestrator" }
  };

  function one(selectors, root) {
    var scope = root || document;
    for (var i = 0; i < selectors.length; i += 1) {
      var node = scope.querySelector(selectors[i]);
      if (node) return node;
    }
    return null;
  }

  function many(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function text(value, fallback) {
    return value === null || value === undefined || value === ""
      ? (fallback === undefined ? "" : String(fallback))
      : String(value);
  }

  function objectOf(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : null;
  }

  function announce(message, error) {
    var node = one(["[data-announcement]", "#announcements", "#status-message"]);
    if (!node) {
      node = document.createElement("div");
      node.id = "announcements";
      node.className = "visually-hidden";
      document.body.appendChild(node);
    }
    node.textContent = text(message);
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", error ? "assertive" : "polite");
  }

  function showState(name, visible, root) {
    many("[data-state='" + name + "'], [data-" + name + "]", root || document).forEach(function (node) {
      node.hidden = !visible;
      node.setAttribute("aria-hidden", visible ? "false" : "true");
    });
  }

  function setBusy(button, busy) {
    if (!button) return;
    if (busy && button.dataset.label === undefined) button.dataset.label = button.textContent;
    button.disabled = !!busy;
    button.setAttribute("aria-busy", busy ? "true" : "false");
    if (busy && button.dataset.busyLabel) button.textContent = button.dataset.busyLabel;
    if (!busy && button.dataset.label !== undefined) {
      button.textContent = button.dataset.label;
      delete button.dataset.label;
    }
  }

  function endpoint(path) { return API_BASE.replace(/\/$/, "") + path; }
  function unavailable() { return "O backend está indisponível. Configure a URL da API para continuar."; }

  function unwrap(payload) {
    if (payload && objectOf(payload.analysis)) return payload.analysis;
    if (payload && objectOf(payload.data) && (payload.data.id || payload.data.analysis_result || payload.data.status)) return payload.data;
    return payload;
  }

  function records(payload) {
    var list = Array.isArray(payload) ? payload : payload && (
      Array.isArray(payload.analyses) ? payload.analyses :
      Array.isArray(payload.items) ? payload.items : Array.isArray(payload.data) ? payload.data : null
    );
    if (list) return list.map(unwrap).filter(objectOf);
    var item = unwrap(payload);
    return objectOf(item) ? [item] : [];
  }

  function normalize(payload) { return records(payload)[0] || null; }
  function resultOf(item) {
    var result = item && (item.analysis_result || item.result || item.results);
    return objectOf(result) ? result : {};
  }
  function dateOf(item) { return item && (item.created_at || item.createdAt || item.date || item.updated_at); }
  function sorted(payload) {
    return records(payload).slice().sort(function (a, b) {
      var first = Date.parse(dateOf(a) || "");
      var second = Date.parse(dateOf(b) || "");
      return (isNaN(second) ? -Infinity : second) - (isNaN(first) ? -Infinity : first);
    });
  }

  function formatDate(value) {
    if (!value) return "—";
    var date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    try { return date.toLocaleString("pt-BR", { dateStyle: "medium", timeStyle: "short" }); }
    catch (_) { return date.toLocaleString("pt-BR"); }
  }

  function statusLabel(value) {
    var raw = text(value, "concluída");
    var labels = {
      completed: "Concluída", complete: "Concluída", success: "Concluída",
      pending: "Pendente", queued: "Na fila", processing: "Em processamento",
      running: "Em processamento", failed: "Falhou", error: "Erro",
      unavailable: "Indisponível", connected: "Conectado", online: "Conectado",
      healthy: "Operacional", degraded: "Instável", offline: "Indisponível"
    };
    return labels[raw.toLowerCase()] || raw;
  }

  function statusKey(value) { return text(value, "concluída").toLowerCase().replace(/\s+/g, "-"); }
  function setText(root, selectors, value, fallback) {
    var node = one(selectors, root);
    if (node) node.textContent = text(value, fallback);
  }

  function request(path, options) {
    if (STATIC) return Promise.reject(new Error(unavailable()));
    var config = Object.assign({}, options || {});
    config.headers = Object.assign({ Accept: "application/json" }, config.headers || {});
    return fetch(endpoint(path), config).then(function (response) {
      return response.text().then(function (raw) {
        var body = null;
        try { body = raw ? JSON.parse(raw) : null; } catch (_) { body = raw; }
        if (!response.ok) {
          var message = body && body.detail ? body.detail : body && body.message ? body.message : "Não foi possível concluir a solicitação (" + response.status + ").";
          throw new Error(String(message));
        }
        return body;
      });
    }).catch(function (error) {
      if (error && error.message) throw error;
      throw new Error("Não foi possível acessar o DevPilot. Verifique sua conexão e tente novamente.");
    });
  }

  function jsonOptions(method, body) {
    return { method: method, headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify(body) };
  }

  function detailSection() { return one(["[data-detail-section]", "[data-analysis-detail]", "#analysis-detail"]); }

  function renderIssues(target, issues) {
    if (!target) return;
    target.textContent = "";
    if (!Array.isArray(issues) || !issues.length) {
      var empty = document.createElement("p");
      empty.className = "empty-state__text";
      empty.textContent = "Nenhum problema encontrado.";
      target.appendChild(empty);
      return;
    }
    var list = document.createElement("ul");
    list.className = "issue-list";
    issues.forEach(function (issue) {
      var item = document.createElement("li");
      item.className = "issue-list__item";
      item.textContent = text(objectOf(issue) ? issue.message || issue.description || issue.title : issue, "Problema sem descrição");
      list.appendChild(item);
    });
    target.appendChild(list);
  }

  function renderSource(target, source) {
    if (!target) return;
    var code = one(["[data-source-code-block]", "pre code[data-source-code]", "code[data-source-code]"], target);
    if (!code) {
      var pre = document.createElement("pre");
      pre.className = "source-code";
      code = document.createElement("code");
      code.setAttribute("data-source-code-block", "true");
      pre.appendChild(code); target.appendChild(pre);
    }
    code.textContent = text(source, "Código-fonte indisponível.");
  }

  function renderRecord(payload) {
    var item = normalize(payload), section = detailSection();
    if (!item || !section) return;
    var result = resultOf(item), status = statusLabel(item.status || result.status);
    section.hidden = false;
    setText(section, ["[data-result-score]", "[data-score]", "[data-detail-score]"], result.score !== undefined ? result.score : item.score, "—");
    setText(section, ["[data-result-summary]", "[data-summary]"], result.summary || item.summary, "Resumo indisponível.");
    setText(section, ["[data-detail-name]", "[data-project-name]"], item.project_name || item.name, "Projeto sem nome");
    setText(section, ["[data-detail-meta]", "[data-task]"], item.task, "Análise de código");
    setText(section, ["[data-created-at]", "[data-detail-date]"], formatDate(dateOf(item)), "—");
    setText(section, ["[data-analysis-id]", "[data-detail-id]"], item.id, "—");
    renderSource(one(["[data-source-output]", "[data-source-container]"], section), item.source_code || item.content);
    var statusNode = one(["[data-result-status]", "[data-status]", "[data-detail-status]"], section);
    if (statusNode) { statusNode.textContent = status; statusNode.dataset.status = statusKey(status); }
    renderIssues(one(["[data-issues-list]", "[data-issues]"], section), result.issues || item.issues);
  }

  function updateAnalysisStatus(id, value) {
    if (!id) return;
    var label = statusLabel(value), key = statusKey(label);
    many("[data-analysis-id='" + String(id).replace(/'/g, "\\'") + "]").forEach(function (node) {
      many("[data-status], .activity-status", node.closest(".history-row, .history-item, .activity-item, li, tr") || node.parentNode).forEach(function (status) {
        status.textContent = label; status.dataset.status = key;
      });
    });
    if (String(state.selectedId) === String(id)) {
      var detailStatus = one(["[data-result-status]", "[data-detail-status]"]);
      if (detailStatus) { detailStatus.textContent = label; detailStatus.dataset.status = key; }
    }
  }

  function renderHistory(payload) {
    var list = one(["[data-history-list]"]);
    if (!list) return;
    var items = sorted(payload), table = list.tagName.toLowerCase() === "tbody";
    many(".history-row, .history-item", list).forEach(function (item) { item.remove(); });
    items.forEach(function (item) {
      var project = text(item.project_name || item.name, "Projeto sem nome"), result = resultOf(item);
      var status = statusLabel(item.status || result.status), score = text(result.score !== undefined ? result.score : item.score, "—");
      var row = document.createElement(table ? "tr" : "li"); row.className = "history-row";
      var button = document.createElement("button"); button.type = "button"; button.className = "history-item__button";
      button.dataset.analysisId = text(item.id); button.textContent = project; button.setAttribute("aria-label", "Abrir análise de " + project);
      if (String(item.id) === String(state.selectedId)) button.classList.add("is-selected");
      if (table) {
        [button, text(item.repository_url || item.source, "Manual"), score, status].forEach(function (value, index) {
          var cell = document.createElement("td");
          if (index === 0) cell.appendChild(value); else cell.textContent = value;
          if (index === 3) { cell.dataset.status = statusKey(status); cell.className = "history-status"; }
          row.appendChild(cell);
        });
        var actionCell = document.createElement("td"), action = document.createElement("button");
        action.type = "button"; action.className = "history-item__button history-item__button--action";
        action.dataset.analysisId = text(item.id); action.textContent = "Ver detalhes"; action.setAttribute("aria-label", "Ver detalhes de " + project);
        actionCell.appendChild(action); row.appendChild(actionCell);
      } else row.appendChild(button);
      list.appendChild(row);
    });
  }

  function renderRecent(payload) {
    var list = one(["[data-recent-list]"]); if (!list) return;
    var items = sorted(payload);
    many(".activity-item, .recent-item", list).forEach(function (item) { item.remove(); });
    showState("recent-empty", !items.length, list.parentNode || document);
    items.slice(0, 5).forEach(function (item) {
      var li = document.createElement("li"); li.className = "activity-item";
      var button = document.createElement("button"); button.type = "button"; button.className = "activity-item__button"; button.dataset.analysisId = text(item.id);
      var main = document.createElement("span"); main.className = "activity-main";
      var title = document.createElement("strong"); title.className = "activity-title"; title.textContent = text(item.project_name || item.name, "Projeto sem nome");
      var meta = document.createElement("span"); meta.className = "activity-meta"; meta.textContent = formatDate(dateOf(item));
      main.appendChild(title); main.appendChild(meta);
      var badge = document.createElement("span"); badge.className = "activity-status"; badge.textContent = statusLabel(item.status || resultOf(item).status); badge.dataset.status = statusKey(badge.textContent);
      button.appendChild(main); button.appendChild(badge); li.appendChild(button); list.appendChild(li);
    });
  }

  function renderMetrics(payload) {
    var items = sorted(payload), scores = items.map(function (item) { var r = resultOf(item); return Number(r.score !== undefined ? r.score : item.score); }).filter(isFinite);
    var average = scores.length ? (scores.reduce(function (a, b) { return a + b; }, 0) / scores.length).toFixed(1) : "—", latest = items[0];
    var total = one(["[data-stat='total-analyses']"]), score = one(["[data-stat='average-score']"]), last = one(["[data-stat='last-analysis']"]), caption = one(["[data-stat='last-analysis-caption']"]);
    if (total) total.textContent = String(items.length); if (score) score.textContent = average; if (last) last.textContent = latest ? formatDate(dateOf(latest)) : "—";
    if (caption) caption.textContent = latest ? text(latest.project_name || latest.name, "Última análise concluída") : "Nenhuma análise registrada";
  }

  function historyState(name, visible) {
    var selector = { loading: "[data-history-loading]", empty: "[data-history-empty]", error: "[data-history-error]" }[name];
    if (selector) many(selector).forEach(function (node) { node.hidden = !visible; });
    var table = one(["[data-history-table-wrap]"]); if (table && (name === "loading" || name === "empty" || name === "error")) table.hidden = visible;
  }

  function loadHistory() {
    var id = ++sequence.history; historyState("loading", true); historyState("empty", false); historyState("error", false);
    return request(CONTRACT.history.path).then(function (payload) {
      if (id !== sequence.history) return state.history;
      state.history = sorted(payload); renderHistory(state.history); renderRecent(state.history); renderMetrics(state.history); historyState("empty", !state.history.length);
      announce(state.history.length ? "Histórico de análises carregado." : "Ainda não há análises."); return state.history;
    }).catch(function (error) { if (id === sequence.history) { historyState("error", true); announce(error.message, true); } throw error; })
      .finally(function () { if (id === sequence.history) historyState("loading", false); });
  }

  function synchronizeStatuses() {
    if (STATIC) return;
    request(CONTRACT.history.path).then(function (payload) {
      sorted(payload).forEach(function (item) { updateAnalysisStatus(item.id, item.status || resultOf(item).status); });
      state.history = sorted(payload);
    }).catch(function () {});
  }

  function loadDetail(id) {
    if (!id) return Promise.resolve(null);
    state.selectedId = id; renderHistory(state.history); showState("detail-loading", true); showState("detail-error", false);
    return request(CONTRACT.detail.path.replace("{id}", encodeURIComponent(id))).then(function (payload) {
      var item = normalize(payload); if (!item) throw new Error("A resposta da API não contém uma análise válida.");
      renderRecord(item); showState("detail-loading", false); showView("detail"); announce("Detalhes da análise carregados."); return item;
    }).catch(function (error) { showState("detail-loading", false); showState("detail-error", true); announce(error.message, true); throw error; });
  }

  function formValues(form) { var values = {}; new FormData(form).forEach(function (value, key) { values[key] = value; }); return values; }

  function createAnalysis(values) {
    var body = { task: text(values.task, "code").trim(), project_name: text(values.project_name).trim(), source_code: text(values.source_code) };
    if (!body.task || !body.project_name || !body.source_code.trim()) return Promise.reject(new Error("Informe a tarefa, o nome do projeto e o código-fonte."));
    ["repository_url", "branch", "file_path"].forEach(function (key) { if (values[key]) body[key] = String(values[key]); });
    return request(CONTRACT.create.path, jsonOptions(CONTRACT.create.method, body));
  }

  function clearValidation(form) {
    many("[aria-invalid='true']", form).forEach(function (field) { field.removeAttribute("aria-invalid"); field.removeAttribute("aria-describedby"); });
    many(".field-error, [data-field-error], [data-error-for]", form).forEach(function (error) { error.remove(); });
  }

  function repositorySelection(form) {
    var select = one(["#repository-file", "[data-repository-file]", "[name='file_path']"], form), path = select ? select.value : "";
    var file = state.repositoryFiles.filter(function (item) { return (typeof item === "string" ? item : item.path || item.name) === path; })[0];
    var source = file && typeof file === "object" ? file.source_code || file.content || "" : "";
    var sourceField = one(["textarea[name='source_code']", "[data-source-code]"], form);
    return { path: path, source: source || text(sourceField && sourceField.value) };
  }

  function validate(form, repository) {
    var valid = true; clearValidation(form);
    many("[required]", form).forEach(function (field) {
      if (!field.disabled && !String(field.value || "").trim()) {
        valid = false; field.setAttribute("aria-invalid", "true");
        var message = document.createElement("span"); message.className = "field-error"; message.textContent = "Este campo é obrigatório.";
        message.id = (field.id || field.name || "campo") + "-erro"; field.setAttribute("aria-describedby", message.id); field.parentNode.appendChild(message);
      }
    });
    if (repository && !repositorySelection(form).path) { valid = false; announce("Selecione um arquivo do repositório.", true); }
    if (!valid) announce("Corrija os campos destacados.", true); return valid;
  }

  function submitForm(form, values) {
    if (STATIC) { announce(unavailable(), true); return; }
    if (!values && !validate(form, false)) return;
    var button = form.querySelector("[type='submit']"), panel = form.closest("[data-analysis-panel], .analysis-panel, .workflow-panel") || form;
    setBusy(button, true); showState("loading", true, panel); showState("error", false, panel);
    createAnalysis(values || formValues(form)).then(function (payload) {
      var item = normalize(payload); if (!item) throw new Error("A API não retornou uma análise válida.");
      renderRecord(item); state.selectedId = item.id || null;
      return loadHistory().catch(function () {}).then(function () { showState("success", true, panel); announce("Análise concluída com sucesso."); showView(item.id ? "detail" : "history"); });
    }).catch(function (error) { showState("error", true, panel); announce(error.message, true); }).finally(function () { setBusy(button, false); showState("loading", false, panel); });
  }

  function loadRepository(form) {
    if (STATIC) { announce(unavailable(), true); return Promise.reject(new Error(unavailable())); }
    var button = one(["[data-load-repository]", "[data-action='load-repository']"], form), values = formValues(form);
    var repository = text(values.repository_url || values.repository || values.url).trim();
    if (!repository) { announce("Informe a URL do repositório GitHub.", true); return Promise.reject(new Error("URL do repositório ausente.")); }
    var id = ++sequence.repository; setBusy(button, true); announce("Carregando arquivos do repositório.");
    return request(form.getAttribute("data-load-endpoint") || CONTRACT.repository.path, jsonOptions(CONTRACT.repository.method, { repository_url: repository, branch: text(values.branch) })).then(function (payload) {
      if (id !== sequence.repository) return payload;
      var files = payload && (payload.files || payload.repository_files || payload.items || payload.data) || [];
      state.repositoryFiles = Array.isArray(files) ? files : [];
      var select = one(["#repository-file", "[data-repository-file]", "[name='file_path']"], form);
      if (select) {
        select.textContent = ""; var placeholder = document.createElement("option"); placeholder.value = ""; placeholder.textContent = "Selecione um arquivo"; placeholder.disabled = true; placeholder.selected = true; select.appendChild(placeholder);
        state.repositoryFiles.forEach(function (file) { var path = typeof file === "string" ? file : file.path || file.name || ""; if (path) { var option = document.createElement("option"); option.value = path; option.textContent = path; select.appendChild(option); } });
        select.disabled = false;
      }
      announce("Arquivos do repositório carregados."); return payload;
    }).catch(function (error) { announce(error.message, true); throw error; }).finally(function () { if (id === sequence.repository) setBusy(button, false); });
  }

  function showView(name, updateUrl) {
    var requested = name || "overview", sections = many("[data-view-section]"), links = many("[data-view], [data-nav], [data-view-target], [data-tab], [data-tab-target]");
    var valid = sections.some(function (section) { return section.dataset.viewSection === requested; }) || links.some(function (link) { return (link.dataset.view || link.dataset.nav || link.dataset.viewTarget || link.dataset.tab || link.dataset.tabTarget) === requested; });
    state.view = valid ? requested : "overview";
    sections.forEach(function (section) { var active = section.dataset.viewSection === state.view; section.hidden = !active; section.setAttribute("aria-hidden", active ? "false" : "true"); section.classList.toggle("is-active", active); });
    links.forEach(function (link) { var target = link.dataset.view || link.dataset.nav || link.dataset.viewTarget || link.dataset.tab || link.dataset.tabTarget, active = target === state.view; link.classList.toggle("is-active", active); if (link.dataset.tab !== undefined || link.dataset.tabTarget !== undefined) link.setAttribute("aria-selected", active ? "true" : "false"); if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current"); });
    many("[data-sidebar], .sidebar").forEach(function (sidebar) { sidebar.classList.remove("is-open"); });
    if (updateUrl !== false && window.history && window.history.replaceState) window.history.replaceState(null, "", "#" + state.view);
  }

  function updateStatus(value, label) {
    var status = statusLabel(value), key = statusKey(status);
    many("[data-connection-status]").forEach(function (node) { node.textContent = label || status; node.dataset.status = key; });
    many("[data-connection-dot], [data-status-dot], .status-dot").forEach(function (node) { node.dataset.status = key; node.classList.toggle("is-connected", key === "conectado" || key === "operacional"); node.classList.toggle("is-unavailable", key === "indisponível"); });
  }

  function init(options) {
    if (started) return; started = true; options = options || {};
    var html = document.documentElement, body = document.body, config = Object.assign({}, window.DEVPILOT_CONFIG || {}, window.DevPilotConfig || {});
    API_BASE = text(options.apiBase || html.dataset.apiBase || body.dataset.apiBase || config.apiBaseUrl || config.API_BASE_URL).trim();
    STATIC = html.dataset.staticFrontend === "true" || body.dataset.staticFrontend === "true" || window.location.protocol === "file:";
    updateStatus(STATIC ? "unavailable" : "connected", STATIC ? "Indisponível" : "Todos os sistemas operacionais");
    var form = one(["[data-analysis-form]", "#analysis-form"]);
    if (form) form.addEventListener("submit", function (event) { event.preventDefault(); submitForm(form); });
    var github = one(["[data-github-form]"]);
    if (github) {
      github.addEventListener("submit", function (event) { event.preventDefault(); if (validate(github, true)) { var values = formValues(github), selected = repositorySelection(github); values.file_path = selected.path; values.source_code = selected.source; submitForm(github, values); } });
      var loader = one(["[data-load-repository]", "[data-action='load-repository']"], github); if (loader) loader.addEventListener("click", function (event) { event.preventDefault(); loadRepository(github).catch(function () {}); });
      var fileSelect = one(["#repository-file", "[data-repository-file]"], github); if (fileSelect) fileSelect.addEventListener("change", function () { var selected = repositorySelection(github), sourceField = one(["textarea[name='source_code']", "[data-source-code]"], github); if (sourceField && selected.source) sourceField.value = selected.source; });
    }
    document.addEventListener("click", function (event) {
      var target = event.target.closest ? event.target.closest("[data-analysis-id], [data-view], [data-nav], [data-view-target], [data-tab], [data-tab-target], [data-action]") : null; if (!target) return;
      var action = target.dataset.action;
      if (action === "toggle-sidebar" || action === "open-sidebar") { event.preventDefault(); many("[data-sidebar], .sidebar").forEach(function (sidebar) { sidebar.classList.toggle("is-open"); }); return; }
      if (action === "close-sidebar") { event.preventDefault(); many("[data-sidebar], .sidebar").forEach(function (sidebar) { sidebar.classList.remove("is-open"); }); return; }
      if (action === "refresh" || action === "refresh-history" || action === "retry-history") { event.preventDefault(); loadHistory().catch(function () {}); return; }
      if (target.dataset.analysisId) { event.preventDefault(); loadDetail(target.dataset.analysisId).catch(function () {}); return; }
      var view = target.dataset.view || target.dataset.nav || target.dataset.viewTarget || target.dataset.tab || target.dataset.tabTarget; if (view) { event.preventDefault(); showView(view); }
    });
    window.addEventListener("hashchange", function () { showView(window.location.hash.slice(1), false); });
    showView(window.location.hash.slice(1) || "overview", false);
    if (!STATIC) {
      loadHistory().catch(function () {});
      request(CONTRACT.status.path).then(function (value) { var status = value && (value.status || value.state || value.health); updateStatus(status || "connected", "Todos os sistemas operacionais"); }).catch(function () { updateStatus("unavailable", "Indisponível"); });
      statusTimer = window.setInterval(function () { synchronizeStatuses(); request(CONTRACT.status.path).then(function (value) { updateStatus(value && (value.status || value.state || value.health) || "connected"); }).catch(function () { updateStatus("unavailable", "Indisponível"); }); }, 15000);
    }
  }

  window.DevPilotDashboard = { init: init, api: { request: request, createAnalysis: createAnalysis, loadHistory: loadHistory, loadDetail: loadDetail, loadRepository: loadRepository }, renderHistory: renderHistory, renderRecentActivity: renderRecent, renderRecord: renderRecord, showView: showView };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { init(); }); else init();
}());