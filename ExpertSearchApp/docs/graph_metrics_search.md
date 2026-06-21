# Graph metrics in expert search

**Status:** Phase 0 (GEXF lookup) + Phase 1B (build-index degree/PageRank) — implemented.

**Related:** [expert_retrieval_fusion.md](expert_retrieval_fusion.md) · [expert_retrieval_code.md](expert_retrieval_code.md) · [web_api.md](web_api.md)

---

## 1. Context

The graph export pipeline ([`src/generate_graphs.py`](../src/generate_graphs.py)) builds network types and writes GEXF files for Gephi. Node-level metrics are computed in [`src/graph_io.py`](../src/graph_io.py):

- **`assign_communities`** — greedy modularity clustering; `community` (int) and `community_name` (hub node label)
- **`assign_metrics`** — `degree`, `betweenness_centrality`, `closeness_centrality`, `clustering_coefficient`, `pagerank`

Separately, **`build-index`** computes degree and global PageRank on the **search co-auth graph** and stores them in `profile_graph_metrics.npz`.

All loading and merging lives in **[`src/retrieval/graph_metrics.py`](../src/retrieval/graph_metrics.py)**.

Precomputed GEXF outputs live under `data/graphs/` (gitignored) or in `data/graphs.zip`. Generate with:

```bash
uv run python src/generate_graphs.py --db data/LudzieNaukiDumpDB/new_prof_search.sqlite
```

---

## 2. Two graph systems

Expert search and GEXF exports use **different** co-authorship definitions. Do not treat GEXF PageRank as interchangeable with query-time PPR.

| | Search co-auth graph | Precomputed GEXF |
|---|---|---|
| Built by | `build-index` → [`coauth_edges.npz`](../src/retrieval/coauth_graph.py) | [`generate_graphs.py`](../src/generate_graphs.py) |
| Scope | ~165k indexed profiles, all domains | Domain-filtered subsets (e.g. `researcher_DZ0101N.gexf` ≈ 10k humanities) |
| Edge rule | Any shared publication; weight = count | Researcher graph: min 2 shared pubs; optional domain filter |
| Query signal | Personalized PPR (UI: **Community**) | Global PageRank, centralities, modularity clusters |
| Runtime cost | PPR per query (skippable via `disable_ppr`) | O(1) lookup if loaded at startup |

```
Offline assets                    API startup                         Query time
─────────────────────            ─────────────────                   ──────────
coauth_edges.npz          →      export at build-index      →       PPR (or static PR)
profile_graph_metrics.npz →      preload_graph_metrics      →       display + fusion
data/graphs/*.gexf        →      merge into GraphMetricsStore →     cluster labels, inst. PR
retrieval_artifacts       →      preload BM25/embed         →       BM25 + semantic + fusion
```

When **PPR is disabled** and graph metrics are loaded, the Community fusion weight can use **static co-auth PageRank** from the search graph (build-index) or GEXF instead of query-specific PPR.

---

## 3. Module overview (`graph_metrics.py`)

### Data types

```python
ResearcherGraphMetrics(
    coauth_degree: int,
    network_pagerank: float,
    cluster_id: int | None,
    cluster_name: str | None,
    betweenness: float | None,      # from GEXF; not shown in UI today
    closeness: float | None,
    clustering: float | None,
)
```

`InstitutionGraphMetrics` has the same shape; keyed by institution UUID.

`GraphMetricsStore` holds `researchers: dict[str, ResearcherGraphMetrics]` and `institutions: dict[str, InstitutionGraphMetrics]`.

### Build-index path

During `build_artifacts` ([`pipeline.py`](../src/retrieval/pipeline.py)):

1. Export `coauth_edges.npz` from SQLite co-authorship pairs.
2. Call `export_profile_graph_metrics(adjacency, profile_ids, artifacts_dir)`.
3. Writes `profile_graph_metrics.npz` (`degree`, `pagerank` arrays) aligned with `profile_id_index.json`.
4. Writes `profile_graph_metrics_meta.json` (counts, timing).

Functions: `compute_coauth_degrees`, `compute_global_pagerank`, `load_profile_graph_metrics`.

### GEXF path

At API startup, `load_graph_metrics(graphs_dir)` parses:

- `researcher_*.gexf` → researcher metrics dict
- `institution_full.gexf` → institution metrics dict (optional)

Uses lenient XML parsing (`_parse_gexf_node_attributes`) because some GEXF files declare numeric types inconsistently.

### Merge at startup

```python
preload_graph_metrics(graphs_dir, artifacts_dir)
```

1. Load GEXF store from disk.
2. Load build-index metrics from `artifacts_dir` (if artifacts exist).
3. `merge_researcher_metrics(index_metrics, gexf_metrics)`:
   - **Degree and PageRank:** build-index values win when both exist.
   - **Cluster labels and centralities:** overlaid from GEXF when present.
   - Profiles only in GEXF keep GEXF-only metrics.

Result is cached globally; `get_graph_metrics_store()` returns it during `run_search`.

---

## 4. Precomputed file inventory

| File | Approx. nodes | Full metrics | Node ID type |
|------|---------------|--------------|--------------|
| `researcher_*.gexf` | varies by domain | Yes | Ludzie `profile_id` |
| `institution_full.gexf` | ~755 | Yes | Institution UUID |
| `specialty_full.gexf` | ~25k | Yes | Specialty ID |
| `institution.gexf`, `specialty.gexf` | ~60 each | Partial (viz trim) | — |

Use `*_full.gexf` and `researcher_*.gexf` for search enrichment. Trimmed SVG exports are for visualization only.

### Build-index artifacts (search graph)

| File | Contents |
|------|----------|
| `profile_graph_metrics.npz` | `degree`, `pagerank` arrays, row order = `profile_id_index.json` |
| `profile_graph_metrics_meta.json` | Profile count, degree min/max, build time |

---

## 5. Metric catalog

### Researcher (profile_id)

| Source | Field | UI label | Use |
|--------|-------|----------|-----|
| Build-index | `degree` | Co-auth degree | Display |
| Build-index / GEXF | `pagerank` | Network rank | Display; static fusion when PPR disabled |
| GEXF | `community_name` | Cluster | Display |
| GEXF | `betweenness_centrality` | — | Loaded; UI optional later |
| GEXF | `closeness_centrality` | — | Loaded |
| GEXF | `clustering_coefficient` | — | Loaded |

### Institution (institution_id)

When an institution filter is active, show **Inst. network rank** — max PageRank among filter institutions the profile currently holds (`max_institution_pagerank_for_profile`).

### Specialty

Deferred (profile → specialty join).

---

## 6. Naming conventions (avoid confusion)

| Field / concept | UI label | Not the same as |
|-----------------|----------|-----------------|
| `network_pagerank` | **Network rank** | **Community** score (PPR or static PR in fusion) |
| `cluster_name` | **Cluster** | Query-specific community score |
| `coauth_degree` | **Co-auth degree** | Total publication count |
| `ppr` (fusion component) | **Community** (when PPR enabled) | Global network rank |

When **`disable_ppr=true`**:

- The **Community** column is hidden (`show_community_column=false`).
- Fusion may still use a static graph signal via `network_pagerank` when metrics are loaded (`static_network_fusion=true` in API response).

---

## 7. Integration status

### Phase 0 (implemented)

- Load GEXF at API startup via `graph_metrics.py`
- Display columns: Co-auth degree, Network rank, Cluster
- Static PageRank in fusion when PPR disabled and metrics available
- Env: `POLSCIENCE_GRAPHS_DIR` (default `data/graphs/`)

### Phase 1B (implemented)

- Precompute `degree` + global PageRank on full search graph at `build-index`
- Merge with GEXF at startup (index metrics win for degree/PageRank; GEXF for clusters)

### Future

- Broader `researcher_*.gexf` coverage across domains
- Specialty graph joins
- Optional filters (`min_coauth_degree`, `min_network_pagerank`)

---

## 8. Deployment

1. Run `build-index` (always required for search).
2. Optionally unzip `data/graphs.zip` into `data/graphs/`, or run `generate_graphs.py` for cluster labels and institution metrics.
3. Set `POLSCIENCE_GRAPHS_DIR` if graphs live elsewhere.

If graphs are missing, search still works; cluster column and institution network rank are omitted. Build-index metrics still provide degree and PageRank on the search graph when `profile_graph_metrics.npz` exists.

`GET /api/health` reports `graphs: true` when the directory exists and contains at least one `.gexf` file.

---

## 9. API fields

Search JSON includes when metrics are loaded:

- `graph_metrics: true`
- `static_network_fusion: true` when PPR disabled and static PageRank used in fusion
- `show_community_column: false` when PPR disabled
- Per result: `coauth_degree`, `network_pagerank`, `cluster_name`, optional `institution_network_pagerank`

See [web_api.md](web_api.md) for the full response schema.

---

## 10. Tests

- [`tests/test_gexf_metrics.py`](../tests/test_gexf_metrics.py) — GEXF load, preload merge, institution PageRank helper, static fusion
- [`tests/test_profile_graph_metrics.py`](../tests/test_profile_graph_metrics.py) — build-index export/load, merge preference rules

Both import from `src.retrieval.graph_metrics` (unified module).
