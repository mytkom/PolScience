# PolScience

Expert discovery and publication graph tooling over the [Ludzie Nauki](https://ludzie.nauka.gov.pl/) research dump.

## Setup

Install dependencies (creates `.venv`):

```bash
uv sync --extra retrieval
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

## Data

```bash
uv run python data/download_db.py
uv run python data/assess_jepa_feasibility.py
```

## Other docs

- [Expert retrieval fusion](docs/expert_retrieval_fusion.md) — BM25 + embeddings + PPR
- [JEPA design](docs/jepa.md) — deferred until abstracts are available

## Tests

```bash
uv run python -m unittest discover -s tests -v
```
