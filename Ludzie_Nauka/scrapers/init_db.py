from __future__ import annotations

import sqlite3
from pathlib import Path


DB_NAME = "ludzie_nauka.sqlite3"


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # =========================================================
    # Metadata / run info
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)

    # =========================================================
    # Queue of generated search URLs (from generator_url.py)
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS search_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        institution TEXT NOT NULL,
        discipline TEXT,
        degree_code TEXT,
        page_number INTEGER NOT NULL,
        url TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'pending',
        profiles_found INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_error TEXT
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_search_pages_status
    ON search_pages(status);
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_search_pages_institution_discipline
    ON search_pages(institution, discipline, degree_code, page_number);
    """)

    # =========================================================
    # Main profile table
    # profile_id from the site is the key safeguard
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT NOT NULL UNIQUE,
        slug TEXT,
        profile_url TEXT NOT NULL UNIQUE,

        full_name TEXT,
        breadcrumb_name TEXT,
        orcid TEXT,
        orcid_url TEXT,

        raw_html_path TEXT,
        raw_json_path TEXT,

        first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_scraped_at TEXT,

        scrape_status TEXT NOT NULL DEFAULT 'discovered',
        scrape_version TEXT,
        source_search_page_id INTEGER,

        FOREIGN KEY (source_search_page_id) REFERENCES search_pages(id)
            ON DELETE SET NULL
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_profiles_scrape_status
    ON profiles(scrape_status);
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_profiles_full_name
    ON profiles(full_name);
    """)

    # =========================================================
    # Top-level summary / current profile info
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS profile_summary (
        profile_id TEXT PRIMARY KEY,
        current_employment_summary_json TEXT,
        discipline_summary_json TEXT,
        specializations_json TEXT,
        tab_menu_json TEXT,
        external_profiles_json TEXT,
        tag_cloud_json TEXT,
        coworkers_json TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (profile_id) REFERENCES profiles(profile_id)
            ON DELETE CASCADE
    );
    """)

    # =========================================================
    # Employment history
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS employment_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT NOT NULL,
        row_order INTEGER NOT NULL,
        period TEXT,
        duration TEXT,
        institution TEXT,
        institution_url TEXT,
        source_json TEXT,
        UNIQUE(profile_id, row_order),
        FOREIGN KEY (profile_id) REFERENCES profiles(profile_id)
            ON DELETE CASCADE
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_employment_profile_id
    ON employment_history(profile_id);
    """)

    # =========================================================
    # Degrees and titles
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS degrees_titles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT NOT NULL,
        row_order INTEGER NOT NULL,
        year TEXT,
        degree_or_title TEXT,
        details_json TEXT,
        linked_entities_json TEXT,
        source_json TEXT,
        UNIQUE(profile_id, row_order),
        FOREIGN KEY (profile_id) REFERENCES profiles(profile_id)
            ON DELETE CASCADE
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_degrees_profile_id
    ON degrees_titles(profile_id);
    """)

    # =========================================================
    # Memberships
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS memberships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT NOT NULL,
        row_order INTEGER NOT NULL,
        role TEXT,
        membership_name TEXT,
        membership_url TEXT,
        period TEXT,
        organization_path TEXT,
        source_json TEXT,
        UNIQUE(profile_id, row_order),
        FOREIGN KEY (profile_id) REFERENCES profiles(profile_id)
            ON DELETE CASCADE
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_memberships_profile_id
    ON memberships(profile_id);
    """)

    # =========================================================
    # Publications preview scraped from profile page
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS publications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT NOT NULL,
        row_order INTEGER NOT NULL,
        title TEXT,
        title_url TEXT,
        authors TEXT,
        publication_type TEXT,
        year TEXT,
        doi TEXT,
        doi_url TEXT,
        source TEXT,
        UNIQUE(profile_id, row_order),
        FOREIGN KEY (profile_id) REFERENCES profiles(profile_id)
            ON DELETE CASCADE
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_publications_profile_id
    ON publications(profile_id);
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_publications_doi
    ON publications(doi);
    """)

    # =========================================================
    # Research work (author / promoter / reviewer)
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS research_work (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT NOT NULL,
        category TEXT NOT NULL,   -- author / promoter / reviewer
        row_order INTEGER NOT NULL,
        title TEXT,
        title_url TEXT,
        description TEXT,
        source TEXT,
        UNIQUE(profile_id, category, row_order),
        FOREIGN KEY (profile_id) REFERENCES profiles(profile_id)
            ON DELETE CASCADE
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_research_work_profile_id
    ON research_work(profile_id);
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_research_work_category
    ON research_work(category);
    """)

    # =========================================================
    # Scrape attempt log
    # One row per attempt, useful for retries/debugging
    # =========================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS scrape_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id TEXT,
        profile_url TEXT,
        status TEXT NOT NULL,   -- started / success / failed / skipped
        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at TEXT,
        error_message TEXT,
        worker_name TEXT,
        scraper_version TEXT,
        FOREIGN KEY (profile_id) REFERENCES profiles(profile_id)
            ON DELETE SET NULL
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_scrape_runs_profile_id
    ON scrape_runs(profile_id);
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_scrape_runs_status
    ON scrape_runs(status);
    """)

    # =========================================================
    # Trigger: keep updated_at fresh on search_pages updates
    # =========================================================
    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS trg_search_pages_updated_at
    AFTER UPDATE ON search_pages
    FOR EACH ROW
    BEGIN
        UPDATE search_pages
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.id;
    END;
    """)

    conn.commit()


def seed_meta(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    meta_items = {
        "db_name": "ludzie_nauka",
        "db_version": "1",
        "project_note": "Scraping public researcher profiles from ludzie.nauka.gov.pl",
    }

    for key, value in meta_items.items():
        cur.execute("""
        INSERT INTO app_meta(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value;
        """, (key, value))

    conn.commit()


def main() -> None:
    db_path = Path(__file__).parent / DB_NAME
    conn = get_connection(db_path)

    try:
        create_schema(conn)
        seed_meta(conn)
        print(f"Database initialized: {db_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()