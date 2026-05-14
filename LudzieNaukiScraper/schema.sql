PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS degree_titles (
    code TEXT PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scientific_domains (
    code TEXT PRIMARY KEY,
    label_en TEXT,
    label_pl TEXT,
    parent_code TEXT REFERENCES scientific_domains (code)
);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    given_name TEXT,
    surname TEXT,
    prefix TEXT,
    second_name TEXT,
    calculated_edu_level TEXT,
    about_me_pl TEXT,
    about_me_en TEXT,
    orcid TEXT,
    degree_code TEXT REFERENCES degree_titles (code),
    domain_code TEXT REFERENCES scientific_domains (code),
    is_stub INTEGER NOT NULL DEFAULT 0 CHECK (is_stub IN (0, 1))
);

CREATE TABLE IF NOT EXISTS profile_domain_disciplines (
    profile_id TEXT NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    domain_code TEXT NOT NULL REFERENCES scientific_domains (code),
    discipline_code TEXT NOT NULL REFERENCES scientific_domains (code),
    PRIMARY KEY (profile_id, discipline_code)
);

CREATE TABLE IF NOT EXISTS specialties (
    id TEXT PRIMARY KEY,
    label_pl TEXT,
    label_en TEXT
);

CREATE TABLE IF NOT EXISTS profile_specialties (
    profile_id TEXT NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    specialty_id TEXT NOT NULL REFERENCES specialties (id) ON DELETE CASCADE,
    sort_order INTEGER,
    PRIMARY KEY (profile_id, specialty_id)
);

CREATE TABLE IF NOT EXISTS specialty_aliases (
    ludzie_specialty_id TEXT PRIMARY KEY,
    canonical_specialty_id TEXT NOT NULL REFERENCES specialties (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_specialty_aliases_canonical ON specialty_aliases (canonical_specialty_id);

CREATE TABLE IF NOT EXISTS publications (
    id TEXT PRIMARY KEY,
    title TEXT,
    abstract TEXT,
    year INTEGER,
    doi TEXT,
    journal_name TEXT,
    pages TEXT,
    publication_type TEXT,
    url TEXT,
    detail_fetched INTEGER NOT NULL DEFAULT 0 CHECK (detail_fetched IN (0, 1))
);

CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL,
    language_code TEXT NOT NULL DEFAULT '',
    UNIQUE (term, language_code)
);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS authorship (
    profile_id TEXT NOT NULL REFERENCES profiles (id),
    publication_id TEXT NOT NULL REFERENCES publications (id),
    PRIMARY KEY (profile_id, publication_id)
);

CREATE TABLE IF NOT EXISTS profile_keywords (
    profile_id TEXT NOT NULL REFERENCES profiles (id),
    keyword_id INTEGER NOT NULL REFERENCES keywords (id),
    source TEXT NOT NULL CHECK (source IN ('summary', 'extracted')),
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (profile_id, keyword_id, source)
);

CREATE TABLE IF NOT EXISTS profile_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL REFERENCES profiles (id),
    org_id TEXT NOT NULL REFERENCES organizations (id),
    role TEXT,
    start_date INTEGER,
    end_date INTEGER
);

CREATE TABLE IF NOT EXISTS profile_functions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL REFERENCES profiles (id),
    org_id TEXT NOT NULL REFERENCES organizations (id),
    function_name TEXT NOT NULL,
    start_date INTEGER,
    end_date INTEGER
);

CREATE INDEX IF NOT EXISTS idx_profiles_stub ON profiles (is_stub);
CREATE INDEX IF NOT EXISTS idx_profiles_domain ON profiles (domain_code);
CREATE INDEX IF NOT EXISTS idx_authorship_pub ON authorship (publication_id);
CREATE INDEX IF NOT EXISTS idx_memberships_profile ON profile_memberships (profile_id);
CREATE INDEX IF NOT EXISTS idx_functions_profile ON profile_functions (profile_id);
CREATE INDEX IF NOT EXISTS idx_profile_domain_disc ON profile_domain_disciplines (profile_id);

CREATE TABLE IF NOT EXISTS institutions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    object_type TEXT,
    country TEXT,
    voivodeship TEXT,
    city TEXT,
    street TEXT,
    postal_cd TEXT,
    regon TEXT,
    nip TEXT,
    www TEXT,
    email TEXT,
    phone TEXT,
    status TEXT,
    status_code TEXT,
    polon_object_id TEXT,
    institution_uid TEXT,
    manager_name TEXT,
    manager_surname TEXT,
    i_kind_name TEXT,
    u_type_name TEXT,
    data_source TEXT,
    radon_raw_json TEXT,
    student_count INTEGER
);

CREATE TABLE IF NOT EXISTS profile_institutions (
    employment_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    institution_id TEXT NOT NULL REFERENCES institutions (id) ON DELETE CASCADE,
    start_date TEXT,
    end_date TEXT,
    status_employment TEXT,
    internet_link TEXT,
    additional_information TEXT,
    employment_source TEXT,
    ludzie_institution_name TEXT,
    ludzie_institution_initial_name TEXT,
    gremium_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_profile_institutions_profile ON profile_institutions (profile_id);
CREATE INDEX IF NOT EXISTS idx_profile_institutions_institution ON profile_institutions (institution_id);

CREATE TABLE IF NOT EXISTS radon_institution_queue (
    institution_id TEXT PRIMARY KEY,
    ludzie_name TEXT NOT NULL,
    enqueued_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_radon_queue_enqueued ON radon_institution_queue (enqueued_at);

CREATE TABLE IF NOT EXISTS publication_extracted_terms (
    publication_id TEXT NOT NULL REFERENCES publications (id),
    term TEXT NOT NULL,
    language_code TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (publication_id, term, language_code)
);
