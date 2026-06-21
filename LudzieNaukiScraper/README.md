# Ludzie Nauki Scraper

This project downloads public data from [Ludzie Nauki](https://ludzie.nauka.gov.pl/) (the Polish portal of scientists and their work) and stores it in a local SQLite database. The data can then be used for analysis outside the website.

The download is done in several steps, called **passes**. Each pass reads a different part of the portal and writes to the same database file.

## Requirements

- Python 3.10 or newer
- Internet access

Install dependencies from the project folder:

```bash
pip install -r requirements.txt
```

## Basic usage

All commands are run from this folder. You must give a path to a SQLite database file with `--db`. If the file does not exist, it is created.

Run Pass 1 and Pass 2 together (the usual first step):

```bash
python -m ludzie_nauki --db my_database.sqlite
```

Run only one pass:

```bash
python -m ludzie_nauki --db my_database.sqlite --pass1-only
python -m ludzie_nauki --db my_database.sqlite --pass2-only
python -m ludzie_nauki --db my_database.sqlite --pass3-only
python -m ludzie_nauki --db my_database.sqlite --pass4-only
```

Work on a single profile (by its Ludzie Nauki ID):

```bash
python -m ludzie_nauki --db my_database.sqlite --single-profile PROFILE_ID
```

Pass 1 can be limited with filters, for example by scientific domain:

```bash
python -m ludzie_nauki --db my_database.sqlite --pass1-only --domain DZ0102N
```

Institution details from the Radon service are fetched in the background by default. To process the waiting list separately:

```bash
python -m ludzie_nauki --db my_database.sqlite --radon-drain
```

Use `--verbose` for more log output.

## Optional flags and parameters

The flags below are not required for a normal run. They control speed, scope, and how the scraper talks to the portal.

### Rate limiting and retries

The scraper waits between HTTP requests so it does not overload the server. After each Ludzie Nauki request it sleeps for a random time between `--sleep-min` and `--sleep-max` seconds (defaults: 0.5 and 1.0). Radon requests use separate, longer waits: `--radon-sleep-min` and `--radon-sleep-max` (defaults: 1.5 and 3.0).

If a request fails because of a network error or a temporary server response (for example HTTP 429 or 5xx), the scraper retries. The limit is set with `--max-retries` (default: 100).

Example — slower, more cautious crawl:

```bash
python -m ludzie_nauki --db my_database.sqlite --sleep-min 1.0 --sleep-max 2.5 --max-retries 150
```

### Page sizes

List endpoints return results in pages. You can change how many items are requested per page:

| Flag | Default | Used in |
|------|---------|---------|
| `--page-size` | 1000 | Pass 1 profile search |
| `--pub-page-size` | 500 | Pass 2 publications |
| `--project-page-size` | 500 | Pass 4 projects |
| `--patent-page-size` | 500 | Pass 4 patents |

Larger pages mean fewer requests but heavier responses.

### Pass 1 search scope

Pass 1 can be narrowed or tested with these flags:

| Flag | Purpose |
|------|---------|
| `--domain CODE` | Limit search to a scientific domain (repeat for several domains) |
| `--discipline CODE` | Limit search to a discipline (repeat; with manual slices, requires at least one `--domain`) |
| `--degree-title CODE` | Limit search to a degree title (repeat) |
| `--pass1-manual-slices` | Run one search slice from the filters above instead of the full automatic shard crawl |
| `--dictionary-year YEAR` | Year used when loading the domain dictionary for shard crawl (default: 2020) |
| `--max-shards N` | Stop shard crawl after N slices (useful for testing) |
| `--per-sort-row-cap N` | Max profiles taken per surname sort direction per slice (default: 1000) |
| `--max-profiles N` | Stop Pass 1 after enriching N profiles |
| `--concurrency N` | Number of parallel workers in Pass 1 (default: 4) |

Example — test Pass 1 on one domain, at most 50 profiles:

```bash
python -m ludzie_nauki --db my_database.sqlite --pass1-only --domain DZ0102N --max-profiles 50
```

### Pass 3

| Flag | Purpose |
|------|---------|
| `--pass3-max-rounds N` | Stop Pass 3 after N rounds even if stubs remain (default: no limit) |

### Radon institution enrichment

By default, Pass 1 saves institution IDs to a queue and does not call Radon immediately. A separate run fills in institution details:

| Flag | Purpose |
|------|---------|
| `--radon-drain` | Only process the institution queue (no passes) |
| `--radon-drain-limit N` | Process at most N queued institutions, then stop |
| `--radon-live` | Call Radon during Pass 1 instead of queuing (slower, blocks enrichment) |

Example — fill institution data in the background while Pass 1 runs elsewhere:

```bash
python -m ludzie_nauki --db my_database.sqlite --radon-drain
```

### Other

| Flag | Purpose |
|------|---------|
| `--verbose` | Print detailed progress and HTTP debug information |
| `--single-profile ID` | Run on one profile only (skips Pass 1 search crawl) |

Only one of `--pass1-only`, `--pass2-only`, `--pass3-only`, and `--pass4-only` can be used at a time.

## The four passes

### Pass 1 — find and fill in profiles

Pass 1 searches the portal for scientist profiles and saves basic information about each person: name, ORCID, scientific domain, specialties, keywords, memberships, and links to institutions where they work. Ludzie nauki search query results (the only available endpoint) are based on ElasticSearch and thus results are limited to 1000 profiles only. We scrape it by sharding (apply all combination all filters available to get a subset of profiles). To get 2000 profiles per combination we also use sorting by surname (1000 for ascending, 1000 for descending).

Source: `ludzie_nauki/pass1.py`

### Pass 2 — publications

Pass 2 goes through each fully known profile and downloads their publications. For each publication it saves the title, year, DOI, and other fields, and records who authored it.

When a co-author appears on a publication but is not yet in the database, Pass 2 creates a **stub profile** for that person (see below).

Source: `ludzie_nauki/pass2.py`

### Pass 3 — resolve stubs

Pass 3 finds all stub profiles, runs Pass 1 on each of them to fill in their details, then runs Pass 2 to download their publications. It repeats this in rounds until no stubs remain. Each round can create new stubs (for example, co-authors of co-authors), so several rounds may be needed.

Source: `ludzie_nauki/pass3.py`

### Pass 4 — projects and patents

Pass 4 downloads funded projects and patents (industrial property) for each profile. It is meant to be run separately, for example as a backfill after Passes 1–3 are done.

Source: `ludzie_nauki/pass4.py`

## What is a stub?

A **stub** is a profile row that exists in the database but has not yet been fully downloaded from the portal. Stubs are created when Pass 2 (or Pass 4) finds a person on a publication, project, or patent before Pass 1 has visited their profile page. A stub usually has only an ID and a display name.

In the database, stubs are marked with `is_stub = 1`. After Pass 1 runs on a stub, it becomes a normal profile (`is_stub = 0`). Pass 3 exists to process all remaining stubs in bulk.

## Source code layout

| Part | Location | Role |
|------|----------|------|
| Command-line entry point | `ludzie_nauki/__main__.py` | Parses arguments and runs the selected pass |
| Pass 1 | `ludzie_nauki/pass1.py` | Profile search and enrichment |
| Pass 2 | `ludzie_nauki/pass2.py` | Publications and authorship |
| Pass 3 | `ludzie_nauki/pass3.py` | Stub resolution loop |
| Pass 4 | `ludzie_nauki/pass4.py` | Projects and patents |
| Database helpers | `ludzie_nauki/db.py` | Reading and writing SQLite tables |
| HTTP client | `ludzie_nauki/http_client.py` | Requests to Ludzie Nauki and Radon APIs |
| Table definitions | `schema.sql` | SQL schema applied when the database is opened |

## Database output

The main result of the scraper is a **SQLite file** (for example `new_prof_search.sqlite`). You choose the path with `--db`.

Alongside the database, the project keeps:

- **`schema.sql`** — description of all tables and columns. The same file is copied into database release folders for reference.
- **Release folders** (for example `13_06_db_files_2/`) — contain a snapshot SQLite file and a copy of `schema.sql` at a given date. These are the packaged outputs ready for analysis or sharing.

The database holds normalized tables: profiles, institutions, publications, projects, patents, and link tables that connect people to their works. Each publication, project, or patent is stored once even if several profiles share it.

Typical table groups:

- **People:** `profiles`, `profile_specialties`, `profile_keywords`, …
- **Affiliations:** `institutions`, `profile_institutions`
- **Publications:** `publications`, `authorship`
- **Projects:** `projects`, `profile_projects`
- **Patents:** `patents`, `patent_rights`, `profile_patents`, `patent_right_authorship`

Open the SQLite file with any SQLite tool, or use the schema file to see the full list of tables and fields.

## Suggested workflow

1. Run Pass 1 and Pass 2: `python -m ludzie_nauki --db my_database.sqlite`
2. Run Pass 3 until stubs are gone: `python -m ludzie_nauki --db my_database.sqlite --pass3-only`
3. Optionally drain the Radon institution queue: `python -m ludzie_nauki --db my_database.sqlite --radon-drain`
4. Run Pass 4 for projects and patents: `python -m ludzie_nauki --db my_database.sqlite --pass4-only`

Steps can be repeated later; existing rows are updated rather than duplicated.
