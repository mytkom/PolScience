# PolScience

Expert discovery and publication graph tooling over the [Ludzie Nauki](https://ludzie.nauka.gov.pl/) research dump.

## Documentation

**Start here:** **[docs/README.md](docs/README.md)** — onboarding map, repo layout, end-to-end data flow.

| Doc | What it covers |
|-----|----------------|
| [docs/expert_retrieval_fusion.md](docs/expert_retrieval_fusion.md) | Algorithm, defaults, CLI tuning |
| [docs/expert_retrieval_code.md](docs/expert_retrieval_code.md) | Python modules, build/query pipeline |
| [docs/web_api.md](docs/web_api.md) | HTTP API, query params, JSON/CSV, UI |
| [docs/graph_metrics_search.md](docs/graph_metrics_search.md) | GEXF + build-index graph metrics |

## Setup

Install dependencies (creates `.venv`):

```bash
uv sync --extra retrieval --extra api
```

Run commands with **`uv run`** so the project venv is used automatically. Alternatively, activate the venv once:

```bash
source .venv/bin/activate
```

### Database download

Run following commands to download db

```sh
python data/download_db.py
```

Then use `python` / `pip` instead of `uv run` below.

## Expert retrieval (active path)

Topic → ranked list of scientists for polling, using **BM25 + bi-encoder + PPR fusion**.

See **[docs/expert_retrieval_fusion.md](docs/expert_retrieval_fusion.md)** for architecture, defaults, and tuning.  
See **[docs/expert_retrieval_code.md](docs/expert_retrieval_code.md)** for a code walkthrough (modules, query flow, artifacts).  
See **[docs/web_api.md](docs/web_api.md)** for the HTTP API and web UI.  
See **[docs/graph_metrics_search.md](docs/graph_metrics_search.md)** for precomputed network metrics in search.

```bash
# Build indexes for both search modes (once per DB refresh)
# Progress logs go to stderr; use -v for more detail
uv run python scripts/query_experts.py build-index \
  --db data/LudzieNaukiDumpDB/new_prof_search.sqlite

# Quieter: WARNING logs only, no embedding tqdm bar
# uv run python scripts/query_experts.py build-index --quiet

# Specific topic (publication titles; default)
uv run python scripts/query_experts.py query \
  --query "quantum error correction" \
  --top 1000 \
  --output results.csv

# Broad field / specialty terms (profile keywords, domains, institutions)
uv run python scripts/query_experts.py query \
  --search-mode profile \
  --query "nauki biologiczne" \
  --top 1000 \
  --output results_profile.csv
```

Artifacts are written to `data/retrieval_artifacts/` (gitignored).

## Web API and UI

After `build-index`, start the server:

```bash
export POLSCIENCE_DB_PATH=data/LudzieNaukiDumpDB/new_prof_search.sqlite
export POLSCIENCE_ARTIFACTS_DIR=data/retrieval_artifacts
export POLSCIENCE_GRAPHS_DIR=data/graphs
uv run uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
```

After changing filter metadata or upgrading from an older index, rerun **`build-index`** so `corpus.jsonl` includes `pubs_by_year`, `polon_projects_by_year`, and `degree_code`.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) — search in **publications** or **profile** mode, optional **Advanced filters**, CSV export.

At startup (when artifacts exist), the API loads the embedding model once and keeps **both** publications and profile indexes (BM25 + embedding matrices + co-auth graph) in memory, so switching search mode stays fast. Optional: `POLSCIENCE_EAGER_LOAD=1` also runs a tiny probe query per mode (slower boot, warms fusion paths).

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web UI |
| `GET /api/health` | DB and artifacts status |
| `GET /api/search?q=...&mode=profile` | JSON results (optional filters: `min_pubs_since`, `since_year`, `min_polon_projects`, `projects_since_year`, `institution_id`, `min_degree_mgr`) |
| `GET /api/search/export.csv?...` | CSV download |

Full API reference: [docs/web_api.md](docs/web_api.md).

## Data

```bash
uv run python data/download_db.py
uv run python data/assess_jepa_feasibility.py
```

## Other docs

- [Documentation index](docs/README.md) — start here for developers
- [Expert retrieval fusion](docs/expert_retrieval_fusion.md) — BM25 + embeddings + PPR
- [Expert retrieval code](docs/expert_retrieval_code.md) — module walkthrough
- [Web API and UI](docs/web_api.md) — endpoints, params, response schema
- [Graph metrics in search](docs/graph_metrics_search.md) — GEXF + build-index enrichment
- [JEPA design](docs/jepa.md) — deferred until abstracts are available

## Tests

```bash
uv run pytest
```
