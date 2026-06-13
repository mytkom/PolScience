# Expert retrieval fusion (BM25 + bi-encoder + PPR)

**Status:** Active retrieval path for polling scientists by topic query.

**Related:** [expert_retrieval_code.md](expert_retrieval_code.md) (how the Python code works) · [jepa.md](jepa.md) (deferred until abstracts exist) · [assess_jepa_feasibility.py](../data/assess_jepa_feasibility.py) (data quality gate)

---

## 1. Objective

Given a **topic query** (Polish or English), produce a ranked list of **~1,000 scientists** suitable for polling or outreach.

Design priorities:

- **Reranker-focused:** a wide lexical recall stage, then semantic and graph signals refine order.
- **No abstracts required for v1** (titles + keywords + taxonomy + specialties).
- **CPU-viable** indexing; GPU optional for faster embedding build.

---

## 2. Architecture

```
Offline (after DB refresh)
  SQLite dump → scientist corpus → BM25 index + embedding matrix + co-auth graph

Query time
  query → BM25 (top 5000) → bi-encoder cosine on pool → PPR from seeds → weighted fusion → top 1000 CSV
```


| Stage      | Signal                           | Default role             |
| ---------- | -------------------------------- | ------------------------ |
| BM25       | Lexical overlap                  | Recall (`recall_k=5000`) |
| Bi-encoder | Semantic similarity              | Rerank (`w_embed=0.55`)  |
| PPR        | Co-authorship proximity to seeds | Rerank (`w_ppr=0.20`)    |


Default fusion (min-max normalized over the candidate pool):

```
final = 0.25 * norm(bm25) + 0.55 * norm(cosine) + 0.20 * norm(ppr)
```

Optional `--gate-bm25`: multiply `final` by `(ε + norm(bm25))` so graph score cannot rescue off-topic profiles.

---

## 3. Data inputs

Source DB: `data/LudzieNaukiDumpDB/new_prof_search.sqlite` (schema: [schema.sql](../data/LudzieNaukiDumpDB/schema.sql)).


| Source      | Tables                                                                     | Used for            |
| ----------- | -------------------------------------------------------------------------- | ------------------- |
| Titles      | `authorship`, `publications`                                               | Main text           |
| Keywords    | `profile_keywords`, `keywords`                                             | Profile terms       |
| Domain      | `profiles.domain_code`, `profile_domain_disciplines`, `scientific_domains` | Labels + filter     |
| Specialties | `profile_specialties`, `specialties`                                       | Labels              |
| Graph       | `authorship` (self-join)                                                   | Co-authorship edges |
| Filters     | `profiles.is_stub`, pub years                                              | Quality gates       |


**Future:** `publications.abstract`, `publication_extracted_terms` — extend corpus builder only.

Indexed profiles: **`is_stub = 0`** only.

---

## 4. Search modes (`--search-mode`)

Two corpora are built and queried separately. **PPR and the co-authorship graph are shared**; only BM25 / bi-encoder text differs.

| Mode | CLI value | When to use | Document text |
|------|-----------|-------------|-----------------|
| **Publications** | `publications` (default) | Specific topic, paper-level wording | Titles + keywords + domains + specialties |
| **Profile** | `profile` | Broad / exploratory query; user knows the field but not Ludzie Nauki taxonomy | Keywords, domains, disciplines, specialties (2×), institutions, degree label, about-me — **no publication titles** |

Profile mode helps queries like *“biological sciences”* or *“climate policy”* match **specialty and domain labels** via semantic search, even when the exact Polish Ludzie Nauki term is unknown.

Institution names come from `profile_institutions` + `institutions`, and `profile_memberships` + `organizations`.

---

## 5. Scientist document (per mode)

### Publications mode

1. Distinct publication **titles** (deduped; cap 200 / 50k chars).
2. **Keywords** (`profile_keywords`, repeat by `count` up to 5×).
3. **Domain** and **discipline** labels.
4. **Specialty** labels.

### Profile mode

1. **Keywords** (same weighting).
2. **Domain**, **discipline**, **specialty**, **degree** labels (each repeated 2× for lexical emphasis).
3. **Institution** names (each up to 2×).
4. **About me** (`about_me_pl`, `about_me_en`).

Stored per mode under `data/retrieval_artifacts/{publications|profile}/corpus.jsonl`:

```json
{"profile_id": "...", "text": "...", "meta": {"pub_count": 12, "max_year": 2024, "domain_code": "..."}, "search_mode": "profile"}
```

---

## 6. Co-authorship graph

Scientist–scientist edges: co-authored ≥1 paper; weight = shared publication count.

```sql
SELECT a1.profile_id, a2.profile_id, COUNT(DISTINCT a1.publication_id) AS weight
FROM authorship a1
JOIN authorship a2
  ON a1.publication_id = a2.publication_id AND a1.profile_id < a2.profile_id
GROUP BY a1.profile_id, a2.profile_id
```

PPR: personalization mass on top `**seed_k=200**` BM25 hits; restart `**alpha=0.85**`; scores read for **BM25 pool only**.

---

## 7. Artifact layout

Directory: **`data/retrieval_artifacts/`** (gitignored).

**Shared (root):**

| File | Description |
|------|-------------|
| `profile_id_index.json` | Row order (same for both modes) |
| `coauth_edges.npz` | Co-authorship graph |
| `build_manifest.json` | Timestamps, counts, modes built |

**Per mode** (`publications/` and `profile/`):

| File | Description |
|------|-------------|
| `corpus.jsonl` | Scientist documents + meta |
| `bm25_index.pkl` | BM25Okapi index |
| `embeddings.f32.npy` | `(n_profiles, dim)` |
| `embeddings_meta.json` | Model name, dimension |

Legacy flat layout (`corpus.jsonl` at artifact root) is still read as **publications** mode only.


---

## 8. CLI

From repo root (after `uv sync --extra retrieval`):

```bash
# Build both modes (default)
python scripts/query_experts.py build-index \
  --db data/LudzieNaukiDumpDB/new_prof_search.sqlite

# Or one mode only
python scripts/query_experts.py build-index --search-mode profile

# Specific topic → publications mode (default)
python scripts/query_experts.py query \
  --query "quantum error correction" \
  --top 1000 \
  --output results.csv

# Broad / taxonomy-agnostic field terms → profile mode
python scripts/query_experts.py query \
  --search-mode profile \
  --query "nauki biologiczne" \
  --top 1000 \
  --output results_profile.csv

# Tunable weights
python scripts/query_experts.py query \
  --query "..." \
  --w-bm25 0.25 --w-embed 0.55 --w-ppr 0.20 \
  --recall-k 5000 --seed-k 200 \
  --gate-bm25
```

Filters (legacy): `--min-pubs N`, `--domain-code CODE`, `--min-year YYYY` (latest pub year, not count since year).

Structural filters (require **`build-index`** after upgrade so `corpus.jsonl` meta includes `pubs_by_year`, `polon_projects_by_year`, `degree_code`):

| Filter | CLI / API params |
|--------|------------------|
| ≥ n publications since year d | `--min-pubs-since N --since-year YYYY` / `min_pubs_since`, `since_year` |
| ≥ p POLON projects since pd | `--min-polon-projects P --projects-since-year YYYY` / `min_polon_projects`, `projects_since_year` |
| Current affiliation at listed universities | `--institution-id UUID` (repeat) / `institution_id` |
| Master’s and above (MGR+) | `--min-degree-mgr` / `min_degree_mgr=true` |

**Notes:** POLON projects = `project_source='POLON'` only (BWNP archive excluded). MGR+ is a proxy; no explicit PhD-student flag in the dump. Institution filter uses `status_employment='CURRENT'`.

### Web API and UI

```bash
uv sync --extra retrieval --extra api
export POLSCIENCE_DB_PATH=data/LudzieNaukiDumpDB/new_prof_search.sqlite
export POLSCIENCE_ARTIFACTS_DIR=data/retrieval_artifacts
uv run uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
```

Browser: [http://127.0.0.1:8000](http://127.0.0.1:8000) — same search modes, table with name / profile URL / scores, CSV export.  
Implementation details: [expert_retrieval_code.md](expert_retrieval_code.md) § HTTP API.

---

## 9. Default hyperparameters


| Parameter       | Default                                 |
| --------------- | --------------------------------------- |
| `recall_k`      | 5000                                    |
| `seed_k`        | 200                                     |
| `output_k`      | 1000                                    |
| `w_bm25`        | 0.25                                    |
| `w_embed`       | 0.55                                    |
| `w_ppr`         | 0.20                                    |
| PPR `alpha`     | 0.85                                    |
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` |


---

## 10. Evaluation / tuning

1. Create `eval/queries.csv`: `query,profile_id,label` (`label` 1 = should appear in top 1000).
2. Run queries; measure **recall@1000** and **MRR** on labeled pairs.
3. Grid-search `w_bm25`, `w_embed`, `w_ppr` on a small set (5–20 queries) before locking defaults.

---

## 11. Performance (≈150k profiles)


| Step           | Time (order of magnitude)    |
| -------------- | ---------------------------- |
| Corpus + BM25  | Minutes (CPU)                |
| Embeddings     | 10–60 min CPU; faster on GPU |
| Co-auth export | 1–5 min                      |
| Single query   | Seconds                      |


---

## 12. Code map


| Module        | Path                            |
| ------------- | ------------------------------- |
| Code walkthrough | [expert_retrieval_code.md](expert_retrieval_code.md) |
| Search modes  | `src/retrieval/modes.py`        |
| Corpus        | `src/retrieval/corpus.py`       |
| BM25          | `src/retrieval/bm25_index.py`   |
| Embeddings    | `src/retrieval/embeddings.py`   |
| Co-auth graph | `src/retrieval/coauth_graph.py` |
| PPR           | `src/retrieval/ppr.py`          |
| Fusion        | `src/retrieval/fusion.py`       |
| Pipeline      | `src/retrieval/pipeline.py`     |
| CLI           | `scripts/query_experts.py`      |
| HTTP API      | `src/api/app.py`                |
| Web UI        | `src/api/static/`               |


---

## 13. Future work

- Abstract enrichment (OpenAlex) → extend corpus text.
- Cross-encoder rerank on top-50.
- Learning-to-rank on `[bm25, cosine, ppr, pub_count, recency]`.
- Email enrichment from Ludzie Nauki API.
- JEPA training after abstract coverage is sufficient (see [jepa.md](jepa.md)).

