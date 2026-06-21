const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const resultsWrap = document.getElementById("results-wrap");
const resultsBody = document.getElementById("results-body");
const resultsHeader = document.getElementById("results-header");
const metaEl = document.getElementById("meta");
const csvBtn = document.getElementById("csv-btn");
const searchBtn = document.getElementById("search-btn");

let lastSearchParams = null;

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

function communityColumnTitle(payload) {
  if (payload.static_network_fusion) {
    return "Static co-auth PageRank (Community weight)";
  }
  return "Personalized PageRank on co-authorship graph";
}

function appendFilterAndGraphHeaders(headers, payload) {
  const filterColumns = payload.filter_columns;
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
  if (payload.graph_metrics) {
    headers.push(
      { label: "Co-auth degree", className: "num", title: "Number of distinct co-authors in the indexed co-authorship graph" },
      { label: "Network rank", className: "num", title: "Global PageRank on the search co-auth graph (query-independent)" },
      { label: "Cluster", title: "Modularity community hub label from offline graph exports (GEXF), when available" }
    );
    if (filterColumns && filterColumns.institutions) {
      headers.push({
        label: "Inst. network rank",
        className: "num",
        title: "Institution PageRank from GEXF for matched filter institutions",
      });
    }
  }
}

function appendFilterAndGraphCells(cells, payload, row) {
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
  if (payload.graph_metrics) {
    cells.push(
      `<td class="num">${row.coauth_degree == null ? "" : escapeHtml(String(row.coauth_degree))}</td>`,
      `<td class="num">${row.network_pagerank == null ? "" : formatScore(row.network_pagerank)}</td>`,
      `<td>${escapeHtml(row.cluster_name || "")}</td>`
    );
    if (fc && fc.institutions) {
      cells.push(
        `<td class="num">${row.institution_network_pagerank == null ? "" : formatScore(row.institution_network_pagerank)}</td>`
      );
    }
  }
}

function buildTableHeaders(payload) {
  const headers = [
    { label: "Rank", className: "num" },
    { label: "Name" },
    { label: "Email" },
    { label: "Profile" },
    { label: "Final", className: "num" },
    { label: "Keywords", className: "num", title: "Lexical keyword overlap (BM25)" },
    { label: "Semantic", className: "num", title: "Embedding cosine similarity" },
  ];
  if (payload.show_community_column) {
    headers.push({
      label: "Community",
      className: "num",
      title: communityColumnTitle(payload),
    });
  }
  appendFilterAndGraphHeaders(headers, payload);
  headers.push({ label: "ID" });
  return headers;
}

function renderTableHeader(payload) {
  resultsHeader.innerHTML = "";
  for (const header of buildTableHeaders(payload)) {
    const th = document.createElement("th");
    th.textContent = header.label;
    if (header.className) th.className = header.className;
    if (header.title) th.title = header.title;
    resultsHeader.appendChild(th);
  }
}

function renderResults(payload) {
  renderTableHeader(payload);
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
    ];
    if (payload.show_community_column) {
      cells.push(`<td class="num">${formatScore(row.ppr)}</td>`);
    }
    appendFilterAndGraphCells(cells, payload, row);
    cells.push(`<td><code>${escapeHtml(row.profile_id)}</code></td>`);
    tr.innerHTML = cells.join("");
    resultsBody.appendChild(tr);
  }
  const w = payload.weights;
  const weightLine = w
    ? `Weights: ${formatPercent(w.keywords)} Keywords · ${formatPercent(w.semantic)} Semantic · ${formatPercent(w.community)} Community`
    : "";
  const staticLine = payload.static_network_fusion
    ? " · Community weight uses static co-auth PageRank (query PPR disabled)"
    : "";
  metaEl.textContent = `Mode: ${payload.search_mode} · ${payload.count} results for “${payload.query}”${weightLine ? ` · ${weightLine}` : ""}${staticLine}`;
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
    Number(params.w_bm25) + Number(params.w_embed) + Number(params.w_ppr);
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
