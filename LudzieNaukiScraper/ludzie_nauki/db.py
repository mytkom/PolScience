from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from ludzie_nauki.radon import flatten_radon_institution
from ludzie_nauki.specialty_labels import specialty_sig_en, specialty_sig_pl

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)


def enqueue_radon_task(conn: sqlite3.Connection, institution_id: str, ludzie_name: str) -> None:
    """Queue a Ludzie institution UUID for deferred Radon portal-search (deduped by id)."""
    iid = str(institution_id).strip()
    if not iid:
        return
    name = (ludzie_name or "unknown").strip() or "unknown"
    conn.execute(
        """
        INSERT INTO radon_institution_queue (institution_id, ludzie_name, enqueued_at)
        VALUES (?, ?, ?)
        ON CONFLICT(institution_id) DO NOTHING
        """,
        (iid, name, time.time()),
    )


def radon_queue_delete(conn: sqlite3.Connection, institution_id: str) -> None:
    conn.execute("DELETE FROM radon_institution_queue WHERE institution_id = ?", (str(institution_id).strip(),))


def radon_queue_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM radon_institution_queue").fetchone()
    return int(row["c"]) if row else 0


def list_institution_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT id FROM institutions ORDER BY id").fetchall()
    return [str(r[0]) for r in rows if r[0] is not None and str(r[0]).strip()]


def upsert_scientific_domain(
    conn: sqlite3.Connection,
    code: str,
    *,
    label_en: Optional[str] = None,
    label_pl: Optional[str] = None,
    parent_code: Optional[str] = None,
) -> None:
    if not code:
        return
    conn.execute(
        """
        INSERT INTO scientific_domains (code, label_en, label_pl, parent_code)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
          label_en = COALESCE(excluded.label_en, scientific_domains.label_en),
          label_pl = COALESCE(excluded.label_pl, scientific_domains.label_pl),
          parent_code = COALESCE(excluded.parent_code, scientific_domains.parent_code)
        """,
        (code, label_en, label_pl, parent_code),
    )


def ensure_domain(conn: sqlite3.Connection, code: str | None, label: str | None = None) -> None:
    """Legacy: treat single label as Polish (search dictionaries are PL)."""
    if not code:
        return
    upsert_scientific_domain(conn, code, label_pl=label or code)


def ensure_degree_title(conn: sqlite3.Connection, code: str | None, label: str | None = None) -> None:
    if not code:
        return
    conn.execute(
        """
        INSERT INTO degree_titles (code, label)
        VALUES (?, COALESCE(?, ?))
        ON CONFLICT(code) DO UPDATE SET label = excluded.label
        """,
        (code, label, code),
    )


def upsert_profile(
    conn: sqlite3.Connection,
    profile_id: str,
    *,
    given_name: str | None = None,
    surname: str | None = None,
    prefix: str | None = None,
    second_name: str | None = None,
    calculated_edu_level: str | None = None,
    about_me_pl: str | None = None,
    about_me_en: str | None = None,
    orcid: str | None = None,
    degree_code: str | None = None,
    domain_code: str | None = None,
    is_stub: int = 0,
) -> None:
    ensure_domain(conn, domain_code)
    ensure_degree_title(conn, degree_code)
    conn.execute(
        """
        INSERT INTO profiles (
            id, given_name, surname, prefix, second_name, calculated_edu_level,
            about_me_pl, about_me_en, orcid, degree_code, domain_code, is_stub
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          given_name = excluded.given_name,
          surname = excluded.surname,
          prefix = excluded.prefix,
          second_name = excluded.second_name,
          calculated_edu_level = excluded.calculated_edu_level,
          about_me_pl = COALESCE(excluded.about_me_pl, profiles.about_me_pl),
          about_me_en = COALESCE(excluded.about_me_en, profiles.about_me_en),
          orcid = COALESCE(excluded.orcid, profiles.orcid),
          degree_code = COALESCE(excluded.degree_code, profiles.degree_code),
          domain_code = COALESCE(excluded.domain_code, profiles.domain_code),
          is_stub = CASE WHEN excluded.is_stub = 0 THEN 0 ELSE profiles.is_stub END
        """,
        (
            profile_id,
            given_name,
            surname,
            prefix,
            second_name,
            calculated_edu_level,
            about_me_pl,
            about_me_en,
            orcid,
            degree_code,
            domain_code,
            is_stub,
        ),
    )


def profile_exists(conn: sqlite3.Connection, profile_id: str) -> bool:
    pid = str(profile_id).strip()
    if not pid:
        return False
    row = conn.execute("SELECT 1 AS x FROM profiles WHERE id = ? LIMIT 1", (pid,)).fetchone()
    return row is not None


def profile_is_stub(conn: sqlite3.Connection, profile_id: str) -> bool:
    pid = str(profile_id).strip()
    if not pid:
        return False
    row = conn.execute("SELECT is_stub FROM profiles WHERE id = ? LIMIT 1", (pid,)).fetchone()
    if row is None:
        return False
    v = row["is_stub"]
    return int(v or 0) == 1


def list_stub_profile_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT id FROM profiles WHERE is_stub = 1 ORDER BY id").fetchall()
    out: list[str] = []
    for r in rows:
        pid = str(r["id"]).strip()
        if pid:
            out.append(pid)
    return out


def merge_specialty_labels_into(
    conn: sqlite3.Connection,
    specialty_id: str,
    label_pl: Optional[str],
    label_en: Optional[str],
) -> None:
    """Prefer longest non-empty label strings when merging onto canonical specialty row."""
    row = conn.execute(
        "SELECT label_pl, label_en FROM specialties WHERE id = ?", (specialty_id,)
    ).fetchone()

    def pick(cur: Optional[str], new: Optional[str]) -> Optional[str]:
        nc = (new or "").strip()
        cc = (cur or "").strip()
        if not nc:
            return cur if cc else None
        if not cc:
            return nc
        return nc if len(nc) >= len(cc) else cc

    if row is None:
        lp = (label_pl or "").strip() or None
        le = (label_en or "").strip() or None
        conn.execute(
            "INSERT INTO specialties (id, label_pl, label_en) VALUES (?, ?, ?)",
            (specialty_id, lp, le),
        )
        return

    lp = pick(row["label_pl"], label_pl)
    le = pick(row["label_en"], label_en)
    conn.execute(
        "UPDATE specialties SET label_pl = ?, label_en = ? WHERE id = ?",
        (lp, le, specialty_id),
    )


def resolve_specialty_id_for_profile(
    conn: sqlite3.Connection,
    ludzie_specialty_id: str,
    label_pl: Optional[str],
    label_en: Optional[str],
) -> str:
    """Map Ludzie specialtyId to canonical specialties.id (sig PL or sig EN match); upsert alias when needed."""
    sid = str(ludzie_specialty_id).strip()
    if not sid:
        raise ValueError("empty ludzie specialty id")

    row = conn.execute(
        "SELECT canonical_specialty_id FROM specialty_aliases WHERE ludzie_specialty_id = ?",
        (sid,),
    ).fetchone()
    if row:
        canon = str(row["canonical_specialty_id"])
        merge_specialty_labels_into(conn, canon, label_pl, label_en)
        return canon

    sig_pl = specialty_sig_pl(label_pl)
    sig_en = specialty_sig_en(label_en)

    bucket: set[str] = set()
    for r in conn.execute("SELECT id, label_pl, label_en FROM specialties").fetchall():
        oid = str(r["id"])
        sp = specialty_sig_pl(r["label_pl"])
        se = specialty_sig_en(r["label_en"])
        if sig_pl and sp == sig_pl:
            bucket.add(oid)
        if sig_en and se == sig_en:
            bucket.add(oid)

    if bucket:
        canon = min(bucket)
        if canon != sid:
            conn.execute(
                """
                INSERT OR IGNORE INTO specialty_aliases (ludzie_specialty_id, canonical_specialty_id)
                VALUES (?, ?)
                """,
                (sid, canon),
            )
        merge_specialty_labels_into(conn, canon, label_pl, label_en)
        return canon

    conn.execute(
        """
        INSERT INTO specialties (id, label_pl, label_en)
        VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          label_pl = COALESCE(excluded.label_pl, specialties.label_pl),
          label_en = COALESCE(excluded.label_en, specialties.label_en)
        """,
        (sid, label_pl, label_en),
    )
    return sid


def get_keyword_id(conn: sqlite3.Connection, term: str, language_code: str = "") -> int:
    t = term.strip()
    if not t:
        raise ValueError("empty keyword")
    lc = (language_code or "").strip()
    row = conn.execute(
        "SELECT id FROM keywords WHERE term = ? AND language_code = ? LIMIT 1",
        (t, lc),
    ).fetchone()
    if row:
        return int(row[0])
    cur = conn.execute("INSERT INTO keywords (term, language_code) VALUES (?, ?)", (t, lc))
    return int(cur.lastrowid)


def replace_profile_summary_keywords(
    conn: sqlite3.Connection, profile_id: str, items: list[tuple[str, int]]
) -> None:
    conn.execute("DELETE FROM profile_keywords WHERE profile_id = ? AND source = 'summary'", (profile_id,))
    for term, count in items:
        if not term or not term.strip():
            continue
        kid = get_keyword_id(conn, term.strip(), "")
        c = max(1, int(count))
        conn.execute(
            """
            INSERT INTO profile_keywords (profile_id, keyword_id, source, count)
            VALUES (?, ?, 'summary', ?)
            ON CONFLICT(profile_id, keyword_id, source) DO UPDATE SET
              count = profile_keywords.count + excluded.count
            """,
            (profile_id, kid, c),
        )


def bump_extracted_keyword(
    conn: sqlite3.Connection, profile_id: str, term: str, language_code: str = "", delta: int = 1
) -> None:
    t = term.strip()
    if not t:
        return
    kid = get_keyword_id(conn, t, language_code)
    conn.execute(
        """
        INSERT INTO profile_keywords (profile_id, keyword_id, source, count)
        VALUES (?, ?, 'extracted', ?)
        ON CONFLICT(profile_id, keyword_id, source) DO UPDATE SET
          count = profile_keywords.count + excluded.count
        """,
        (profile_id, kid, max(1, delta)),
    )


def delete_child_rows_for_profile(conn: sqlite3.Connection, profile_id: str) -> None:
    conn.execute("DELETE FROM profile_institutions WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM profile_domain_disciplines WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM profile_specialties WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM profile_memberships WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM profile_functions WHERE profile_id = ?", (profile_id,))


def insert_organization(conn: sqlite3.Connection, org_id: str, name: str) -> None:
    conn.execute(
        """
        INSERT INTO organizations (id, name) VALUES (?, ?)
        ON CONFLICT(id) DO UPDATE SET name = excluded.name
        """,
        (org_id, name),
    )


def upsert_institution_from_radon_payload(
    conn: sqlite3.Connection,
    payload: Optional[dict[str, Any]],
    *,
    ludzie_id: str,
    ludzie_name: str,
) -> str:
    """Upsert institutions row; Radon JSON optional. PK = Polon / ludzie institution UUID."""
    ludzie_id = str(ludzie_id).strip()
    ludzie_name = (ludzie_name or "unknown").strip() or "unknown"
    if isinstance(payload, dict) and (payload.get("id") or (payload.get("object") or {}).get("institutionUuid")):
        f = flatten_radon_institution(payload)
        iid = str(f["id"] or ludzie_id)
        f["id"] = iid
        f.setdefault("name", ludzie_name)
    else:
        iid = ludzie_id
        f = {
            "id": iid,
            "name": ludzie_name,
            "object_type": None,
            "country": None,
            "voivodeship": None,
            "city": None,
            "street": None,
            "postal_cd": None,
            "regon": None,
            "nip": None,
            "www": None,
            "email": None,
            "phone": None,
            "status": None,
            "status_code": None,
            "polon_object_id": None,
            "institution_uid": None,
            "manager_name": None,
            "manager_surname": None,
            "i_kind_name": None,
            "u_type_name": None,
            "data_source": None,
            "radon_raw_json": None,
        }
    conn.execute(
        """
        INSERT INTO institutions (
            id, name, object_type, country, voivodeship, city, street, postal_cd,
            regon, nip, www, email, phone, status, status_code,
            polon_object_id, institution_uid, manager_name, manager_surname,
            i_kind_name, u_type_name, data_source, radon_raw_json
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          name = COALESCE(excluded.name, institutions.name),
          object_type = COALESCE(excluded.object_type, institutions.object_type),
          country = COALESCE(excluded.country, institutions.country),
          voivodeship = COALESCE(excluded.voivodeship, institutions.voivodeship),
          city = COALESCE(excluded.city, institutions.city),
          street = COALESCE(excluded.street, institutions.street),
          postal_cd = COALESCE(excluded.postal_cd, institutions.postal_cd),
          regon = COALESCE(excluded.regon, institutions.regon),
          nip = COALESCE(excluded.nip, institutions.nip),
          www = COALESCE(excluded.www, institutions.www),
          email = COALESCE(excluded.email, institutions.email),
          phone = COALESCE(excluded.phone, institutions.phone),
          status = COALESCE(excluded.status, institutions.status),
          status_code = COALESCE(excluded.status_code, institutions.status_code),
          polon_object_id = COALESCE(excluded.polon_object_id, institutions.polon_object_id),
          institution_uid = COALESCE(excluded.institution_uid, institutions.institution_uid),
          manager_name = COALESCE(excluded.manager_name, institutions.manager_name),
          manager_surname = COALESCE(excluded.manager_surname, institutions.manager_surname),
          i_kind_name = COALESCE(excluded.i_kind_name, institutions.i_kind_name),
          u_type_name = COALESCE(excluded.u_type_name, institutions.u_type_name),
          data_source = COALESCE(excluded.data_source, institutions.data_source),
          radon_raw_json = COALESCE(excluded.radon_raw_json, institutions.radon_raw_json)
        """,
        (
            str(f["id"]),
            f["name"] or ludzie_name,
            f["object_type"],
            f["country"],
            f["voivodeship"],
            f["city"],
            f["street"],
            f["postal_cd"],
            f["regon"],
            f["nip"],
            f["www"],
            f["email"],
            f["phone"],
            f["status"],
            f["status_code"],
            f["polon_object_id"],
            f["institution_uid"],
            f["manager_name"],
            f["manager_surname"],
            f["i_kind_name"],
            f["u_type_name"],
            f["data_source"],
            f["radon_raw_json"],
        ),
    )
    return str(f["id"])


def insert_profile_employment(
    conn: sqlite3.Connection,
    profile_id: str,
    employment: dict[str, Any],
    institution_id: str,
) -> None:
    eid = employment.get("employmentId")
    if not eid:
        return
    inst = employment.get("institution") or {}
    add = employment.get("additionalInformation")
    conn.execute(
        """
        INSERT INTO profile_institutions (
            employment_id, profile_id, institution_id,
            start_date, end_date, status_employment,
            internet_link, additional_information, employment_source,
            ludzie_institution_name, ludzie_institution_initial_name, gremium_id
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(employment_id) DO UPDATE SET
          profile_id = excluded.profile_id,
          institution_id = excluded.institution_id,
          start_date = excluded.start_date,
          end_date = excluded.end_date,
          status_employment = excluded.status_employment,
          internet_link = excluded.internet_link,
          additional_information = excluded.additional_information,
          employment_source = excluded.employment_source,
          ludzie_institution_name = excluded.ludzie_institution_name,
          ludzie_institution_initial_name = excluded.ludzie_institution_initial_name,
          gremium_id = excluded.gremium_id
        """,
        (
            str(eid),
            profile_id,
            str(institution_id),
            employment.get("startDate"),
            employment.get("endDate"),
            employment.get("statusEmployment"),
            employment.get("internetLink"),
            str(add) if add is not None else None,
            employment.get("employmentSource"),
            inst.get("name"),
            inst.get("initialName"),
            inst.get("gremiumId"),
        ),
    )


def profile_has_current_employment_at(
    conn: sqlite3.Connection, profile_id: str, institution_id: str
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM profile_institutions
        WHERE profile_id = ? AND institution_id = ? AND COALESCE(status_employment,'') = 'CURRENT'
        LIMIT 1
        """,
        (profile_id, institution_id),
    ).fetchone()
    return row is not None


def seed_dictionaries(conn: sqlite3.Connection, dictionaries: dict[str, Any]) -> None:
    if not dictionaries:
        return
    for d in dictionaries.get("degreeTitles") or []:
        if isinstance(d, dict) and d.get("code"):
            ensure_degree_title(conn, d["code"], d.get("label"))
    for entry in dictionaries.get("domains") or []:
        dom = entry.get("domain") or {}
        dcode, dlabel = dom.get("code"), dom.get("label")
        if dcode:
            ensure_domain(conn, dcode, dlabel)
        for disc in entry.get("disciplines") or []:
            cc = disc.get("code")
            ll = disc.get("label")
            if cc:
                upsert_scientific_domain(conn, cc, label_pl=ll or cc, parent_code=dcode)


def upsert_publication_minimal(
    conn: sqlite3.Connection,
    pub_id: str,
    *,
    title: str | None,
    abstract: str | None = None,
    year: int | None,
    doi: str | None,
    journal_name: str | None,
    pages: str | None,
    publication_type: str | None,
    url: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO publications (id, title, abstract, year, doi, journal_name, pages, publication_type, url, detail_fetched)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(id) DO UPDATE SET
          title = COALESCE(excluded.title, publications.title),
          abstract = COALESCE(excluded.abstract, publications.abstract),
          year = COALESCE(excluded.year, publications.year),
          doi = COALESCE(excluded.doi, publications.doi),
          journal_name = COALESCE(excluded.journal_name, publications.journal_name),
          pages = COALESCE(excluded.pages, publications.pages),
          publication_type = COALESCE(excluded.publication_type, publications.publication_type),
          url = COALESCE(excluded.url, publications.url)
        """,
        (pub_id, title, abstract, year, doi, journal_name, pages, publication_type, url),
    )


def set_publication_detail_fetched(conn: sqlite3.Connection, pub_id: str, fetched: bool = True) -> None:
    conn.execute(
        "UPDATE publications SET detail_fetched = ? WHERE id = ?",
        (1 if fetched else 0, pub_id),
    )


def publication_detail_fetched(conn: sqlite3.Connection, pub_id: str) -> bool:
    row = conn.execute("SELECT detail_fetched FROM publications WHERE id = ?", (pub_id,)).fetchone()
    return bool(row and row[0] == 1)


def clear_publication_extracted_terms(conn: sqlite3.Connection, pub_id: str) -> None:
    conn.execute("DELETE FROM publication_extracted_terms WHERE publication_id = ?", (pub_id,))


def add_publication_extracted_term(
    conn: sqlite3.Connection, pub_id: str, term: str, language_code: str = ""
) -> None:
    t = term.strip()
    if not t:
        return
    lc = (language_code or "").strip()
    conn.execute(
        """
        INSERT OR IGNORE INTO publication_extracted_terms (publication_id, term, language_code)
        VALUES (?, ?, ?)
        """,
        (pub_id, t, lc),
    )


def list_publication_extracted_terms(conn: sqlite3.Connection, pub_id: str) -> list[tuple[str, str]]:
    return [
        (str(r[0]), str(r[1]))
        for r in conn.execute(
            """
            SELECT term, language_code FROM publication_extracted_terms
            WHERE publication_id = ? ORDER BY language_code, term
            """,
            (pub_id,),
        ).fetchall()
    ]


def insert_authorship(conn: sqlite3.Connection, profile_id: str, publication_id: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO authorship (profile_id, publication_id)
        VALUES (?, ?)
        """,
        (profile_id, publication_id),
    )


def profile_ids_for_pass2(
    conn: sqlite3.Connection,
    *,
    domain_codes: Optional[list[str]] = None,
    discipline_codes: Optional[list[str]] = None,
) -> list[str]:
    dom = [str(x).strip() for x in (domain_codes or []) if x and str(x).strip()]
    dis = [str(x).strip() for x in (discipline_codes or []) if x and str(x).strip()]
    if dis and not dom:
        raise ValueError("discipline filter requires at least one domain")
    if not dom:
        rows = conn.execute("SELECT id FROM profiles WHERE is_stub = 0").fetchall()
        return [str(r["id"]) for r in rows]

    placeholders_d = ",".join(["?"] * len(dom))
    if not dis:
        sql = f"""
            SELECT DISTINCT p.id FROM profiles p
            LEFT JOIN profile_domain_disciplines pdd ON pdd.profile_id = p.id
            WHERE p.is_stub = 0
              AND (
                p.domain_code IN ({placeholders_d})
                OR pdd.domain_code IN ({placeholders_d})
              )
        """
        return [str(r["id"]) for r in conn.execute(sql, tuple(dom + dom)).fetchall()]

    placeholders_s = ",".join(["?"] * len(dis))
    sql = f"""
        SELECT DISTINCT p.id FROM profiles p
        INNER JOIN profile_domain_disciplines pdd ON pdd.profile_id = p.id
        WHERE p.is_stub = 0
          AND pdd.domain_code IN ({placeholders_d})
          AND pdd.discipline_code IN ({placeholders_s})
    """
    return [str(r["id"]) for r in conn.execute(sql, tuple(dom + dis)).fetchall()]


def profile_ids_for_pass4(
    conn: sqlite3.Connection,
    *,
    domain_codes: Optional[list[str]] = None,
    discipline_codes: Optional[list[str]] = None,
) -> list[str]:
    return profile_ids_for_pass2(
        conn, domain_codes=domain_codes, discipline_codes=discipline_codes
    )


def upsert_institution_minimal(conn: sqlite3.Connection, institution_id: str, name: str) -> None:
    iid = str(institution_id).strip()
    nm = (name or "unknown").strip() or "unknown"
    if not iid:
        return
    conn.execute(
        """
        INSERT INTO institutions (id, name)
        VALUES (?, ?)
        ON CONFLICT(id) DO UPDATE SET name = COALESCE(excluded.name, institutions.name)
        """,
        (iid, nm),
    )


def upsert_project_minimal(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    title: str | None,
    project_number: str | None = None,
    classification: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    funds: float | None = None,
    project_source: str | None = None,
    edition: str | None = None,
    abstract: str | None = None,
    link_radon: str | None = None,
    entity_showing_uuid: str | None = None,
    entity_showing_name: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO projects (
            id, project_number, title, classification, start_date, end_date, funds,
            project_source, edition, abstract, link_radon, entity_showing_uuid,
            entity_showing_name, detail_fetched
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(id) DO UPDATE SET
          project_number = COALESCE(excluded.project_number, projects.project_number),
          title = COALESCE(excluded.title, projects.title),
          classification = COALESCE(excluded.classification, projects.classification),
          start_date = COALESCE(excluded.start_date, projects.start_date),
          end_date = COALESCE(excluded.end_date, projects.end_date),
          funds = COALESCE(excluded.funds, projects.funds),
          project_source = COALESCE(excluded.project_source, projects.project_source),
          edition = COALESCE(excluded.edition, projects.edition),
          abstract = COALESCE(excluded.abstract, projects.abstract),
          link_radon = COALESCE(excluded.link_radon, projects.link_radon),
          entity_showing_uuid = COALESCE(excluded.entity_showing_uuid, projects.entity_showing_uuid),
          entity_showing_name = COALESCE(excluded.entity_showing_name, projects.entity_showing_name)
        """,
        (
            project_id,
            project_number,
            title,
            classification,
            start_date,
            end_date,
            funds,
            project_source,
            edition,
            abstract,
            link_radon,
            entity_showing_uuid,
            entity_showing_name,
        ),
    )


def project_detail_fetched(conn: sqlite3.Connection, project_id: str) -> bool:
    row = conn.execute("SELECT detail_fetched FROM projects WHERE id = ?", (project_id,)).fetchone()
    return bool(row and row[0] == 1)


def set_project_detail_fetched(conn: sqlite3.Connection, project_id: str, fetched: bool = True) -> None:
    conn.execute(
        "UPDATE projects SET detail_fetched = ? WHERE id = ?",
        (1 if fetched else 0, project_id),
    )


def replace_project_keywords(conn: sqlite3.Connection, project_id: str, keywords: list[str]) -> None:
    conn.execute("DELETE FROM project_keywords WHERE project_id = ?", (project_id,))
    for kw in keywords:
        t = (kw or "").strip()
        if t:
            conn.execute(
                "INSERT OR IGNORE INTO project_keywords (project_id, keyword) VALUES (?, ?)",
                (project_id, t),
            )


def replace_project_financing(conn: sqlite3.Connection, project_id: str, names: list[str]) -> None:
    conn.execute("DELETE FROM project_financing_institutions WHERE project_id = ?", (project_id,))
    for nm in names:
        t = (nm or "").strip()
        if t:
            conn.execute(
                """
                INSERT OR IGNORE INTO project_financing_institutions (project_id, name)
                VALUES (?, ?)
                """,
                (project_id, t),
            )


def replace_project_implementing(
    conn: sqlite3.Connection,
    project_id: str,
    rows: list[tuple[str | None, str, bool]],
) -> None:
    conn.execute("DELETE FROM project_implementing_institutions WHERE project_id = ?", (project_id,))
    for institution_id, name, is_leader in rows:
        nm = (name or "").strip()
        if not nm:
            continue
        iid = (institution_id or "").strip() or None
        if iid:
            upsert_institution_minimal(conn, iid, nm)
        conn.execute(
            """
            INSERT OR REPLACE INTO project_implementing_institutions
                (project_id, institution_id, name, is_leader)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, iid, nm, 1 if is_leader else 0),
        )


def insert_profile_project(
    conn: sqlite3.Connection,
    profile_id: str,
    project_id: str,
    *,
    roles: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO profile_projects (profile_id, project_id, roles)
        VALUES (?, ?, ?)
        ON CONFLICT(profile_id, project_id) DO UPDATE SET
          roles = COALESCE(excluded.roles, profile_projects.roles)
        """,
        (profile_id, project_id, roles),
    )


def upsert_patent_minimal(
    conn: sqlite3.Connection,
    patent_id: str,
    *,
    title: str | None,
    type_code: str | None = None,
    type_label: str | None = None,
    abstract: str | None = None,
    calculated_language_code: str | None = None,
    patent_source: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO patents (
            id, type_code, type_label, title, abstract,
            calculated_language_code, patent_source, detail_fetched
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(id) DO UPDATE SET
          type_code = COALESCE(excluded.type_code, patents.type_code),
          type_label = COALESCE(excluded.type_label, patents.type_label),
          title = COALESCE(excluded.title, patents.title),
          abstract = COALESCE(excluded.abstract, patents.abstract),
          calculated_language_code = COALESCE(
              excluded.calculated_language_code, patents.calculated_language_code
          ),
          patent_source = COALESCE(excluded.patent_source, patents.patent_source)
        """,
        (
            patent_id,
            type_code,
            type_label,
            title,
            abstract,
            calculated_language_code,
            patent_source,
        ),
    )


def patent_detail_fetched(conn: sqlite3.Connection, patent_id: str) -> bool:
    row = conn.execute("SELECT detail_fetched FROM patents WHERE id = ?", (patent_id,)).fetchone()
    return bool(row and row[0] == 1)


def set_patent_detail_fetched(conn: sqlite3.Connection, patent_id: str, fetched: bool = True) -> None:
    conn.execute(
        "UPDATE patents SET detail_fetched = ? WHERE id = ?",
        (1 if fetched else 0, patent_id),
    )


def upsert_patent_right(
    conn: sqlite3.Connection,
    right_id: str,
    patent_id: str,
    *,
    application_date: str | None = None,
    application_number: str | None = None,
    publication_date: str | None = None,
    publication_number: str | None = None,
    granting_institution_code: str | None = None,
    granting_institution_name: str | None = None,
    granting_institution_country: str | None = None,
    protection_region_code: str | None = None,
    protection_region_name: str | None = None,
    priority_region: str | None = None,
    priority_number: str | None = None,
    link_radon: str | None = None,
    link_uprp: str | None = None,
    link_espacenet: str | None = None,
    entity_showing_id: str | None = None,
    entity_showing_name: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO patent_rights (
            id, patent_id, application_date, application_number, publication_date,
            publication_number, granting_institution_code, granting_institution_name,
            granting_institution_country, protection_region_code, protection_region_name,
            priority_region, priority_number, link_radon, link_uprp, link_espacenet,
            entity_showing_id, entity_showing_name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          patent_id = excluded.patent_id,
          application_date = COALESCE(excluded.application_date, patent_rights.application_date),
          application_number = COALESCE(excluded.application_number, patent_rights.application_number),
          publication_date = COALESCE(excluded.publication_date, patent_rights.publication_date),
          publication_number = COALESCE(excluded.publication_number, patent_rights.publication_number),
          granting_institution_code = COALESCE(
              excluded.granting_institution_code, patent_rights.granting_institution_code
          ),
          granting_institution_name = COALESCE(
              excluded.granting_institution_name, patent_rights.granting_institution_name
          ),
          granting_institution_country = COALESCE(
              excluded.granting_institution_country, patent_rights.granting_institution_country
          ),
          protection_region_code = COALESCE(
              excluded.protection_region_code, patent_rights.protection_region_code
          ),
          protection_region_name = COALESCE(
              excluded.protection_region_name, patent_rights.protection_region_name
          ),
          priority_region = COALESCE(excluded.priority_region, patent_rights.priority_region),
          priority_number = COALESCE(excluded.priority_number, patent_rights.priority_number),
          link_radon = COALESCE(excluded.link_radon, patent_rights.link_radon),
          link_uprp = COALESCE(excluded.link_uprp, patent_rights.link_uprp),
          link_espacenet = COALESCE(excluded.link_espacenet, patent_rights.link_espacenet),
          entity_showing_id = COALESCE(excluded.entity_showing_id, patent_rights.entity_showing_id),
          entity_showing_name = COALESCE(excluded.entity_showing_name, patent_rights.entity_showing_name)
        """,
        (
            right_id,
            patent_id,
            application_date,
            application_number,
            publication_date,
            publication_number,
            granting_institution_code,
            granting_institution_name,
            granting_institution_country,
            protection_region_code,
            protection_region_name,
            priority_region,
            priority_number,
            link_radon,
            link_uprp,
            link_espacenet,
            entity_showing_id,
            entity_showing_name,
        ),
    )


def list_patent_right_ids(conn: sqlite3.Connection, patent_id: str) -> list[str]:
    return [
        str(r[0])
        for r in conn.execute(
            "SELECT id FROM patent_rights WHERE patent_id = ? ORDER BY id",
            (patent_id,),
        ).fetchall()
    ]


def insert_profile_patent(conn: sqlite3.Connection, profile_id: str, patent_id: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO profile_patents (profile_id, patent_id)
        VALUES (?, ?)
        """,
        (profile_id, patent_id),
    )


def insert_patent_right_authorship(
    conn: sqlite3.Connection, profile_id: str, patent_right_id: str
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO patent_right_authorship (profile_id, patent_right_id)
        VALUES (?, ?)
        """,
        (profile_id, patent_right_id),
    )
