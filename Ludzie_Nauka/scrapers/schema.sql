CREATE TABLE app_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
CREATE TABLE search_pages (
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
CREATE TABLE sqlite_sequence(name,seq);
CREATE INDEX idx_search_pages_status
    ON search_pages(status);
CREATE INDEX idx_search_pages_institution_discipline
    ON search_pages(institution, discipline, degree_code, page_number);
CREATE TABLE profiles (
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
CREATE INDEX idx_profiles_scrape_status
    ON profiles(scrape_status);
CREATE INDEX idx_profiles_full_name
    ON profiles(full_name);
CREATE TABLE profile_summary (
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
CREATE TABLE employment_history (
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
CREATE INDEX idx_employment_profile_id
    ON employment_history(profile_id);
CREATE TABLE degrees_titles (
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
CREATE INDEX idx_degrees_profile_id
    ON degrees_titles(profile_id);
CREATE TABLE memberships (
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
CREATE INDEX idx_memberships_profile_id
    ON memberships(profile_id);
CREATE TABLE publications (
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
CREATE INDEX idx_publications_profile_id
    ON publications(profile_id);
CREATE INDEX idx_publications_doi
    ON publications(doi);
CREATE TABLE research_work (
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
CREATE INDEX idx_research_work_profile_id
    ON research_work(profile_id);
CREATE INDEX idx_research_work_category
    ON research_work(category);
CREATE TABLE scrape_runs (
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
CREATE INDEX idx_scrape_runs_profile_id
    ON scrape_runs(profile_id);
CREATE INDEX idx_scrape_runs_status
    ON scrape_runs(status);
CREATE TRIGGER trg_search_pages_updated_at
    AFTER UPDATE ON search_pages
    FOR EACH ROW
    BEGIN
        UPDATE search_pages
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.id;
    END;
