const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const resultsWrap = document.getElementById("results-wrap");
const resultsBody = document.getElementById("results-body");
const metaEl = document.getElementById("meta");
const csvBtn = document.getElementById("csv-btn");
const searchBtn = document.getElementById("search-btn");

let lastSearchParams = null;

function parseWeight(value, fallback) {
  const n = Number.parseFloat(value);
  return Number.isFinite(n) && n >= 0 ? String(n) : String(fallback);
}

function getFormParams() {
  const data = new FormData(form);
  const q = (data.get("q") || "").toString().trim();
  const mode = (data.get("mode") || "publications").toString();
  const top = (data.get("top") || "1000").toString();
  const w_bm25 = parseWeight(data.get("w_bm25"), 0.25);
  const w_embed = parseWeight(data.get("w_embed"), 0.55);
  const w_ppr = parseWeight(data.get("w_ppr"), 0.2);
  return { q, mode, top, w_bm25, w_embed, w_ppr };
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
  return qs.toString();
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

function renderResults(payload) {
  resultsBody.innerHTML = "";
  for (const row of payload.results) {
    const tr = document.createElement("tr");
    const profileLink = row.profile_url
      ? `<a href="${escapeAttr(row.profile_url)}" target="_blank" rel="noopener">Open</a>`
      : "";
    tr.innerHTML = `
      <td class="num">${row.rank}</td>
      <td>${escapeHtml(row.name)}</td>
      <td>${escapeHtml(row.email || "")}</td>
      <td>${profileLink}</td>
      <td class="num">${formatScore(row.final)}</td>
      <td class="num">${formatScore(row.bm25)}</td>
      <td class="num">${formatScore(row.cosine)}</td>
      <td class="num">${formatScore(row.ppr)}</td>
      <td><code>${escapeHtml(row.profile_id)}</code></td>
    `;
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
