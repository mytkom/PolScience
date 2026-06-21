# Expert Search App

Topic → ranked list of scientists for polling, using **BM25 + bi-encoder + PPR fusion** over the [Ludzie Nauki](https://ludzie.nauka.gov.pl/) SQLite dump.

**Prerequisites:** SQLite database from [`../LudzieNaukiScraper`](../LudzieNaukiScraper/). Optional GEXF graph metrics from [`../graphGeneration`](../graphGeneration/).

## Documentation

**Start here:** **[docs/README.md](docs/README.md)** — onboarding map, module layout, data flow.

| Doc | What it covers |
|-----|----------------|
| [docs/expert_retrieval_fusion.md](docs/expert_retrieval_fusion.md) | Algorithm, defaults, CLI tuning |
| [docs/expert_retrieval_code.md](docs/expert_retrieval_code.md) | Python modules, build/query pipeline |
| [docs/web_api.md](docs/web_api.md) | HTTP API, query params, JSON/CSV, UI |
| [docs/graph_metrics_search.md](docs/graph_metrics_search.md) | GEXF + build-index graph metrics |

## Setup

From this directory (`ExpertSearchApp/`):

```bash
uv sync --extra retrieval --extra api
```

Run commands with **`uv run`** so the project venv is used automatically.

### Database

Build or obtain a SQLite dump via the Ludzie Nauki scraper, or download a pre-built dump at monorepo root:

```bash
# from repo root
uv run python data/download_db.py
```

Default DB path (shared monorepo `data/`):  
`../data/LudzieNaukiDumpDB/new_prof_search.sqlite`

## Expert retrieval CLI

```bash
# Build indexes for both search modes (once per DB refresh)
uv run python scripts/query_experts.py build-index \
  --db ../data/LudzieNaukiDumpDB/new_prof_search.sqlite

# Quieter build
# uv run python scripts/query_experts.py build-index --quiet

# Specific topic (publication titles; default)
uv run python scripts/query_experts.py query \
  --query "quantum error correction" \
  --top 1000 \
  --output results.csv

# Broad field / specialty terms (profile mode)
uv run python scripts/query_experts.py query \
  --search-mode profile \
  --query "nauki biologiczne" \
  --top 1000 \
  --output results_profile.csv
```

Artifacts are written to **`../data/retrieval_artifacts/`** (gitignored at monorepo root).

## Web API and UI

After `build-index`:

```bash
export POLSCIENCE_DB_PATH=../data/LudzieNaukiDumpDB/new_prof_search.sqlite
export POLSCIENCE_ARTIFACTS_DIR=../data/retrieval_artifacts
export POLSCIENCE_GRAPHS_DIR=../data/graphs
uv run uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) — search in **publications** or **profile** mode, optional **Advanced filters**, CSV export.

At startup the API preloads the embedding model and **both** mode indexes. Optional: `POLSCIENCE_EAGER_LOAD=1` runs probe queries at boot.

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web UI |
| `GET /api/health` | DB and artifacts status |
| `GET /api/search?q=...&mode=profile` | JSON results |
| `GET /api/search/export.csv?...` | CSV download |

Full API reference: [docs/web_api.md](docs/web_api.md).

## Optional graph metrics

For cluster labels and institution network rank columns, generate GEXF from the sibling project:

```bash
cd ../graphGeneration
uv run python src/generate_graphs.py --db ../data/LudzieNaukiDumpDB/new_prof_search.sqlite
```

See [docs/graph_metrics_search.md](docs/graph_metrics_search.md).

## Tests

```bash
uv run pytest
```

## Environment variables

| Variable | Default (monorepo `data/`) |
|----------|----------------------------|
| `POLSCIENCE_DB_PATH` | `../data/LudzieNaukiDumpDB/new_prof_search.sqlite` |
| `POLSCIENCE_ARTIFACTS_DIR` | `../data/retrieval_artifacts` |
| `POLSCIENCE_GRAPHS_DIR` | `../data/graphs` |
| `POLSCIENCE_EAGER_LOAD` | off |

Paths resolve relative to the monorepo root when using defaults in `src/api/config.py`.
