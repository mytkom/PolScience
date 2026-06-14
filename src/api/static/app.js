const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const resultsWrap = document.getElementById("results-wrap");
const resultsBody = document.getElementById("results-body");
const resultsHeader = document.getElementById("results-header");
const metaEl = document.getElementById("meta");
const csvBtn = document.getElementById("csv-btn");
const searchBtn = document.getElementById("search-btn");
const disablePprInput = document.getElementById("disable_ppr");
const wPprInput = document.getElementById("w_ppr");

let lastSearchParams = null;

function syncPprControls() {
  const disabled = disablePprInput.checked;
  wPprInput.disabled = disabled;
  wPprInput.classList.toggle("disabled-input", disabled);
}

disablePprInput.addEventListener("change", syncPprControls);
syncPprControls();

function parseWeight(value, fallback) {
  const n = Number.parseFloat(value);
  return Number.isFinite(n) && n >= 0 ? String(n) : String(fallback);
}

function optionalIntField(data, name) {
  const raw = (data.get(name) || "").toString().trim();
  if (!raw) return null;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) ? String(n) : null;
}

function parseCommaSeparated(raw) {
  if (!raw) return [];
  return raw
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function getFormParams() {
  const data = new FormData(form);
  const q = (data.get("q") || "").toString().trim();
  const mode = (data.get("mode") || "publications").toString();
  const top = (data.get("top") || "1000").toString();
  const w_bm25 = parseWeight(data.get("w_bm25"), 0.25);
  const w_embed = parseWeight(data.get("w_embed"), 0.55);
  const w_ppr = parseWeight(data.get("w_ppr"), 0.2);
  const min_pubs_since = optionalIntField(data, "min_pubs_since");
  const since_year = optionalIntField(data, "since_year");
  const min_polon_projects = optionalIntField(data, "min_polon_projects");
  const projects_since_year = optionalIntField(data, "projects_since_year");
  const institution_ids = parseCommaSeparated((data.get("institution_ids") || "").toString());
  const institution_names = parseCommaSeparated((data.get("institution_names") || "").toString());
  const min_degree_mgr = data.get("min_degree_mgr") === "on";
  const disable_ppr = data.get("disable_ppr") === "on";
  return {
    q,
    mode,
    top,
    w_bm25,
    w_embed,
    w_ppr,
    disable_ppr,
    min_pubs_since,
    since_year,
    min_polon_projects,
    projects_since_year,
    institution_ids,
    institution_names,
    min_degree_mgr,
  };
}

function buildQueryString(params) {
  const qs = new URLSearchParams({
    q: params.q,
    mode: params.mode,
    top: params.top,
    w_bm25: params.w_bm25,
    w_embed: params.w_embed,
    w_ppr: params.w_ppr,
  });
  if (params.min_pubs_since) qs.set("min_pubs_since", params.min_pubs_since);
  if (params.since_year) qs.set("since_year", params.since_year);
  if (params.min_polon_projects) qs.set("min_polon_projects", params.min_polon_projects);
  if (params.projects_since_year) qs.set("projects_since_year", params.projects_since_year);
  for (const id of params.institution_ids) {
    qs.append("institution_id", id);
  }
  for (const name of params.institution_names) {
    qs.append("institution_name", name);
  }
  if (params.min_degree_mgr) qs.set("min_degree_mgr", "true");
  if (params.disable_ppr) qs.set("disable_ppr", "true");
  return qs.toString();
}

function validatePairedFilters(params) {
  if (Boolean(params.min_pubs_since) !== Boolean(params.since_year)) {
    return "Set both min publications count and since year, or leave both empty.";
  }
  if (Boolean(params.min_polon_projects) !== Boolean(params.projects_since_year)) {
    return "Set both min POLON projects count and since year, or leave both empty.";
  }
  return null;
}

function formatPercent(fraction) {
  return `${Math.round(fraction * 100)}%`;
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function formatScore(value) {
  return Number(value).toFixed(4);
}

function buildTableHeaders(filterColumns) {
  const headers = [
    { label: "Rank", className: "num" },
    { label: "Name" },
    { label: "Email" },
    { label: "Profile" },
    { label: "Final", className: "num" },
    { label: "Keywords", className: "num", title: "Lexical keyword overlap (BM25)" },
    { label: "Semantic", className: "num", title: "Embedding cosine similarity" },
    { label: "Community", className: "num", title: "Personalized PageRank on co-authorship graph" },
  ];
  if (filterColumns) {
    if (filterColumns.pubs_since_year != null) {
      headers.push({
        label: `Pubs since ${filterColumns.pubs_since_year}`,
        className: "num",
      });
    }
    if (filterColumns.projects_since_year != null) {
      headers.push({
        label: `Projects since ${filterColumns.projects_since_year}`,
        className: "num",
      });
    }
    if (filterColumns.institutions) {
      headers.push({ label: "Institutions" });
    }
    if (filterColumns.degree) {
      headers.push({ label: "Degree" });
    }
  }
  headers.push({ label: "ID" });
  return headers;
}

function renderTableHeader(filterColumns) {
  resultsHeader.innerHTML = "";
  for (const header of buildTableHeaders(filterColumns)) {
    const th = document.createElement("th");
    th.textContent = header.label;
    if (header.className) th.className = header.className;
    if (header.title) th.title = header.title;
    resultsHeader.appendChild(th);
  }
}

function renderResults(payload) {
  renderTableHeader(payload.filter_columns);
  resultsBody.innerHTML = "";
  for (const row of payload.results) {
    const tr = document.createElement("tr");
    const profileLink = row.profile_url
      ? `<a href="${escapeAttr(row.profile_url)}" target="_blank" rel="noopener">Open</a>`
      : "";
    const cells = [
      `<td class="num">${row.rank}</td>`,
      `<td>${escapeHtml(row.name)}</td>`,
      `<td>${escapeHtml(row.email || "")}</td>`,
      `<td>${profileLink}</td>`,
      `<td class="num">${formatScore(row.final)}</td>`,
      `<td class="num">${formatScore(row.bm25)}</td>`,
      `<td class="num">${formatScore(row.cosine)}</td>`,
      `<td class="num">${formatScore(row.ppr)}</td>`,
    ];
    const fc = payload.filter_columns;
    if (fc) {
      if (fc.pubs_since_year != null) {
        cells.push(
          `<td class="num">${row.pubs_since_year == null ? "" : escapeHtml(String(row.pubs_since_year))}</td>`
        );
      }
      if (fc.projects_since_year != null) {
        cells.push(
          `<td class="num">${row.projects_since_year == null ? "" : escapeHtml(String(row.projects_since_year))}</td>`
        );
      }
      if (fc.institutions) {
        cells.push(`<td>${escapeHtml(row.institutions || "")}</td>`);
      }
      if (fc.degree) {
        cells.push(`<td>${escapeHtml(row.degree || "")}</td>`);
      }
    }
    cells.push(`<td><code>${escapeHtml(row.profile_id)}</code></td>`);
    tr.innerHTML = cells.join("");
    resultsBody.appendChild(tr);
  }
  const w = payload.weights;
  const weightLine = w
    ? `Weights: ${formatPercent(w.keywords)} Keywords · ${formatPercent(w.semantic)} Semantic · ${formatPercent(w.community)} Community`
    : "";
  metaEl.textContent = `Mode: ${payload.search_mode} · ${payload.count} results for “${payload.query}”${weightLine ? ` · ${weightLine}` : ""}`;
  resultsWrap.classList.remove("hidden");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function escapeAttr(text) {
  return text.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const params = getFormParams();
  if (!params.q) {
    setStatus("Enter a query.", true);
    return;
  }
  const pairedError = validatePairedFilters(params);
  if (pairedError) {
    setStatus(pairedError, true);
    return;
  }
  const weightSum =
    Number(params.w_bm25) +
    Number(params.w_embed) +
    (params.disable_ppr ? 0 : Number(params.w_ppr));
  if (weightSum <= 0) {
    setStatus("Set at least one fusion weight above zero.", true);
    return;
  }
  lastSearchParams = params;
  csvBtn.disabled = true;
  searchBtn.disabled = true;
  setStatus("Searching…");
  resultsWrap.classList.add("hidden");

  try {
    const qs = buildQueryString(params);
    const response = await fetch(`/api/search?${qs}`);
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || response.statusText);
    }
    const payload = await response.json();
    renderResults(payload);
    setStatus(`Done — ${payload.count} experts.`);
    csvBtn.disabled = payload.count === 0;
  } catch (err) {
    setStatus(err.message || "Search failed.", true);
  } finally {
    searchBtn.disabled = false;
  }
});

csvBtn.addEventListener("click", () => {
  if (!lastSearchParams) return;
  const qs = buildQueryString(lastSearchParams);
  window.location.href = `/api/search/export.csv?${qs}`;
});
