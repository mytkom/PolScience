# Graph metrics in expert search

**Status:** Phase 0 — precomputed GEXF lookup at API startup.

**Related:** [expert_retrieval_fusion.md](expert_retrieval_fusion.md) · [expert_retrieval_code.md](expert_retrieval_code.md)

---

## 1. Context

The graph export pipeline ([`src/generate_graphs.py`](../src/generate_graphs.py)) builds three network types and writes GEXF files for Gephi. Node-level metrics are computed in [`src/graph_io.py`](../src/graph_io.py):

- **`assign_communities`** — greedy modularity clustering; `community` (int) and `community_name` (hub node label)
- **`assign_metrics`** — `degree`, `betweenness_centrality`, `closeness_centrality`, `clustering_coefficient`, `pagerank`

Precomputed outputs live under `data/graphs/` (gitignored) or in `data/graphs.zip`. Generate with:

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
Offline assets          API startup              Query time
─────────────────       ─────────────            ──────────
data/graphs/*.gexf  →   load GEXF metrics   →   display columns
retrieval_artifacts →   preload BM25/embed  →   BM25 + semantic + PPR/static PR fusion
```

When **PPR is disabled** and GEXF metrics are loaded, the Community fusion weight uses **static co-auth PageRank** from GEXF instead of query-specific PPR.

---

## 3. Precomputed file inventory

| File | Approx. nodes | Full metrics | Node ID type |
|------|---------------|--------------|--------------|
| `researcher_*.gexf` | varies by domain | Yes | Ludzie `profile_id` |
| `institution_full.gexf` | ~755 | Yes | Institution UUID |
| `specialty_full.gexf` | ~25k | Yes | Specialty ID |
| `institution.gexf`, `specialty.gexf` | ~60 each | Partial (viz trim) | — |

Use `*_full.gexf` and `researcher_*.gexf` for search enrichment. Trimmed SVG exports are for visualization only.

---

## 4. Metric catalog

### Researcher (profile_id)

| GEXF attribute | UI label | Phase 0 use |
|----------------|----------|-------------|
| `degree` | Co-auth degree | Display |
| `pagerank` | Network rank | Display; static fusion when PPR disabled |
| `community_name` | Cluster | Display |
| `betweenness_centrality` | — | Loaded; display optional later |
| `closeness_centrality` | — | Loaded; display optional later |
| `clustering_coefficient` | — | Loaded; display optional later |

### Institution (institution_id)

When an institution filter is active, show **institution network rank** (max PageRank among filter institutions the profile currently holds).

### Specialty

Deferred to Phase 2 (profile → specialty join).

---

## 5. Naming conventions

| GEXF field | UI label | Not the same as |
|------------|----------|-----------------|
| `pagerank` | **Network rank** | **Community** (PPR or static PR used in fusion) |
| `community_name` | **Cluster** | Query-specific community score |
| `degree` | **Co-auth degree** | Total publication count |

---

## 6. Integration roadmap

### Phase 0 (implemented)

- Load `researcher_*.gexf` and `institution_full.gexf` at API startup ([`src/retrieval/gexf_metrics.py`](../src/retrieval/gexf_metrics.py))
- Display columns: Co-auth degree, Network rank, Cluster
- When `disable_ppr=true` and GEXF loaded: Community weight uses static PageRank
- Env: `POLSCIENCE_GRAPHS_DIR` (default `data/graphs/`)

### Phase 1

- Generate more `researcher_{domain}.gexf` files for broader coverage
- Optionally precompute cheap metrics (`degree`, `pagerank`) on full `coauth_edges.npz` at `build-index`

### Phase 2

- Institution metric columns when institution filter active
- Specialty graph joins
- Optional filters (`min_coauth_degree`, `min_network_pagerank`)

---

## 7. Deployment

1. Unzip `data/graphs.zip` into `data/graphs/`, or run `generate_graphs.py`.
2. Set `POLSCIENCE_GRAPHS_DIR` if graphs live elsewhere.
3. If graphs are missing, search still works; graph columns and static fusion are omitted.

`GET /api/health` reports `graphs: true` when the directory exists and contains at least one `.gexf` file.

---

## 8. API fields

Search JSON includes when graphs are loaded:

- `graph_metrics: true`
- `static_network_fusion: true` when PPR disabled and static PageRank used in fusion
- Per result: `coauth_degree`, `network_pagerank`, `cluster_name`, optional `institution_network_pagerank`
