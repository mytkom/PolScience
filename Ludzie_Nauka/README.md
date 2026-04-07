URL of interest : https://ludzie.nauka.gov.pl/ln/

Advanced research explained : https://ludzie.nauka.gov.pl/wp/pomoc/jak-korzystac-z-wyszukiwarki/

# Ludzie Nauka Scraper

This project scrapes academic profiles from the Polish science portal **ludzie.nauka.gov.pl** and stores the results in a structured **SQLite** database.

## Setup

Initialize the database first:

```bash
python3 init_db.py
```

## Workflow

### 1. Generate search URLs
`generator_url.py` builds all search result URLs from:
- `instytucje.json` (institutions)
- `dyscypliny.json` (disciplines)

Output:
- `generated_urls.json`

### 2. Load search pages into the database
`load_search_pages.py` inserts all generated search result pages into the `search_pages` table.

### 3. Scrape search result pages
`scraper.py` visits each search page, extracts profile links, and inserts unique people into the `profiles` table.

Important optimization:
- if page `n` has zero results, all pages `k > n` for the same `(institution, discipline, degree)` combination are marked as `skipped`

### 4. Scrape profile pages
`profile_scraper.py` visits each discovered profile and extracts structured data such as:
- identity
- ORCID
- degrees and academic titles
- employment history
- memberships
- publications
- research work

Raw files are also saved:
- `data/raw_html/`
- `data/raw_json/`

---

## Main database tables

### `search_pages`
Stores all search result URLs and their scraping status.

Key fields:
- `institution`
- `discipline`
- `degree_code`
- `page_number`
- `url`
- `status` (`pending`, `done`, `skipped`, `failed`)
- `profiles_found`

### `profiles`
Stores one row per discovered person.

Key fields:
- `profile_id` ( that one is imposed by the website, we don't choose it !)
- `full_name`
- `profile_url`
- `scrape_status` (`discovered`, `running`, `scraped`, `failed`)

### `profile_summary`
Stores one-row-per-profile JSON summary blocks.

### Child tables
These store structured profile sub-sections:
- `employment_history`
- `degrees_titles`
- `memberships`
- `publications`
- `research_work`

### `scrape_runs`
Stores execution history for profile scraping attempts.

---

## How to use the DB

Open the database:

Once you download it 

```bash
sqlite3 ludzie_nauka.sqlite3