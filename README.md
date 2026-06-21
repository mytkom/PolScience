# Polish Science Database

We aim in this project to create a database of Polish science (scientists with their publications, projects, patents and employments). We use central databases like [Ludzie Nauki](https://ludzie.nauka.gov.pl/) (People of Science) and enrich them with repository pages of specific universities and email information from universities' contact books (where available online).

A second goal is a search tool useful for Research4Revenue cohort discovery: classical criteria (publication counts, recent projects) plus semantic search over research topics.

We also generate graph representations of the database for further study.

## Design decisions

- **SQLite** for our data volume (few GB): flexible, no hosting required, relational schema fits scientists ↔ publications ↔ institutions.
- **FastAPI** for the expert search UI: runs locally today, can be hosted later.

## Project structure

Each subproject is self-contained with its own README. Run commands from the subproject folder unless noted.

| Subproject | Description |
|------------|-------------|
| [**LudzieNaukiScraper**](LudzieNaukiScraper/) | 4-pass Python scraper using the Ludzie Nauki JSON API → SQLite. Rate limiting, concurrent workers, optional Pass 4 (projects/patents). |
| [**PolUni**](PolUni/) | Java CLI: RAD-on / POL-on APIs → institution CSVs for DB enrichment. |
| [**PWrEmailDataEnrichment**](PWrEmailDataEnrichment/) | PoC: PWr contact book scraper + Python merge into SQLite by name match. |
| [**graphGeneration**](graphGeneration/) | Offline co-authorship / institution / specialty GEXF export from SQLite. |
| [**ExpertSearchApp**](ExpertSearchApp/) | BM25 + semantic + PPR expert search over Ludzie Nauki profiles; FastAPI web UI and CSV export. Requires a SQLite DB (from LudzieNaukiScraper) and optional GEXF from graphGeneration. |

## Tests and development

See each subproject's README for setup (`uv sync`, `pytest`, etc.).

```bash
# Example: Ludzie Nauki scraper
cd LudzieNaukiScraper && python -m ludzie_nauki --help

# Example: expert search (after build-index)
cd ExpertSearchApp && uv sync --extra retrieval --extra api && uv run pytest
```

## License

See [LICENSE](LICENSE).
