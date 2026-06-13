"""Build per-scientist searchable text from the Ludzie Nauki SQLite schema.

Two assembly strategies (SearchMode):
  publications — titles + keywords + taxonomy (paper-level search).
  profile      — keywords, specialties, domains, institutions, about-me (no titles).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from src.graph.publication_graph import ensure_graph_indexes
from src.retrieval.logging_config import get_build_logger, log_step
from src.retrieval.modes import SearchMode

MAX_TITLES = 200
MAX_TEXT_CHARS = 50_000
MAX_KEYWORD_REPEAT = 5
MAX_INSTITUTION_REPEAT = 2

CORPUS_FILENAME = "corpus.jsonl"
PROFILE_INDEX_FILENAME = "profile_id_index.json"


@dataclass(slots=True)
class ScientistDocument:
    profile_id: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)
    search_mode: str = SearchMode.PUBLICATIONS.value


def mode_artifact_dir(artifacts_dir: Path, mode: SearchMode) -> Path:
    return artifacts_dir / mode.value


def _label(*parts: str | None) -> str:
    for part in parts:
        if part and str(part).strip():
            return str(part).strip()
    return ""


def _cap_titles(titles: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for raw in titles:
        title = str(raw or "").strip()
        if not title:
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(title)
        if len(unique) >= MAX_TITLES:
            break
    return unique


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _assemble_publications_text(
    titles: list[str],
    keywords: list[tuple[str, int]],
    domains: list[str],
    specialties: list[str],
) -> str:
    parts: list[str] = []
    parts.extend(_cap_titles(titles))
    for term, count in keywords:
        repeat = min(max(1, int(count)), MAX_KEYWORD_REPEAT)
        parts.extend([term] * repeat)
    parts.extend(domains)
    parts.extend(specialties)
    text = " ".join(parts)
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    return text


def _assemble_profile_text(
    keywords: list[tuple[str, int]],
    domains: list[str],
    specialties: list[str],
    institutions: list[str],
    about_me: list[str],
    degree_labels: list[str],
) -> str:
    """Profile-centric document for exploratory / taxonomy-agnostic queries (no titles)."""
    parts: list[str] = []
    for term, count in keywords:
        repeat = min(max(1, int(count)), MAX_KEYWORD_REPEAT)
        parts.extend([term] * repeat)
    for label in _dedupe_preserve_order(domains + specialties + degree_labels):
        parts.extend([label, label])
    for name in _dedupe_preserve_order(institutions):
        parts.extend([name] * MAX_INSTITUTION_REPEAT)
    parts.extend(_dedupe_preserve_order(about_me))
    text = " ".join(parts)
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    return text


@dataclass(slots=True)
class _ProfileBundle:
    profile_ids: list[str]
    domain_codes: dict[str, str | None]
    degree_codes_by_profile: dict[str, str | None]
    titles_by_profile: dict[str, list[str]]
    pub_stats: dict[str, dict[str, Any]]
    pubs_by_year_by_profile: dict[str, dict[int, int]]
    polon_projects_by_year_by_profile: dict[str, dict[int, int]]
    keywords_by_profile: dict[str, list[tuple[str, int]]]
    domains_by_profile: dict[str, list[str]]
    specialties_by_profile: dict[str, list[str]]
    institutions_by_profile: dict[str, list[str]]
    about_me_by_profile: dict[str, list[str]]
    degree_labels_by_profile: dict[str, list[str]]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _load_profile_bundle(conn: sqlite3.Connection) -> _ProfileBundle | None:
    """Single pass over DB tables; shared by both SearchMode assembly paths."""
    logger = get_build_logger()
    ensure_graph_indexes(conn)
    conn.row_factory = sqlite3.Row

    with log_step(logger, "SQL: load non-stub profiles"):
        profile_rows = conn.execute(
        """
        SELECT id, domain_code, about_me_pl, about_me_en, degree_code
        FROM profiles
        WHERE is_stub = 0
        ORDER BY id
        """
        ).fetchall()
    if not profile_rows:
        logger.warning("No non-stub profiles found in database")
        return None

    profile_ids = [str(row["id"]) for row in profile_rows]
    logger.info("Loaded %d non-stub profiles", len(profile_ids))
    domain_codes = {str(row["id"]): row["domain_code"] for row in profile_rows}

    about_me_by_profile: dict[str, list[str]] = defaultdict(list)
    degree_codes_by_profile: dict[str, str | None] = {}
    for row in profile_rows:
        pid = str(row["id"])
        pl = _label(row["about_me_pl"])
        en = _label(row["about_me_en"])
        if pl:
            about_me_by_profile[pid].append(pl)
        if en and en.casefold() != pl.casefold() if pl else True:
            about_me_by_profile[pid].append(en)
        degree_codes_by_profile[pid] = row["degree_code"]

    titles_by_profile: dict[str, list[str]] = defaultdict(list)
    with log_step(logger, "SQL: authorship + publication titles"):
        title_rows = 0
        for row in conn.execute(
            """
            SELECT a.profile_id, p.title
            FROM authorship a
            JOIN publications p ON p.id = a.publication_id
            WHERE p.title IS NOT NULL AND TRIM(p.title) != ''
            """
        ):
            title_rows += 1
            pid = str(row["profile_id"])
            if pid in domain_codes:
                titles_by_profile[pid].append(str(row["title"]))
        logger.info(
            "Titles: %d authorship rows → %d profiles with ≥1 title",
            title_rows,
            len(titles_by_profile),
        )

    pub_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"pub_count": 0, "max_year": None}
    )
    for pid, titles in titles_by_profile.items():
        pub_stats[pid]["pub_count"] = len(_cap_titles(titles))

    with log_step(logger, "SQL: publication years per profile"):
        for row in conn.execute(
            """
            SELECT a.profile_id, MAX(p.year) AS max_year
            FROM authorship a
            JOIN publications p ON p.id = a.publication_id
            WHERE p.year IS NOT NULL
            GROUP BY a.profile_id
            """
        ):
            pid = str(row["profile_id"])
            if pid in domain_codes:
                pub_stats[pid]["max_year"] = row["max_year"]

    pubs_by_year_by_profile: dict[str, dict[int, int]] = defaultdict(dict)
    with log_step(logger, "SQL: publication counts by year"):
        pub_year_rows = 0
        for row in conn.execute(
            """
            SELECT a.profile_id, p.year, COUNT(DISTINCT p.id) AS cnt
            FROM authorship a
            JOIN publications p ON p.id = a.publication_id
            WHERE p.year IS NOT NULL
            GROUP BY a.profile_id, p.year
            """
        ):
            pub_year_rows += 1
            pid = str(row["profile_id"])
            if pid in domain_codes:
                pubs_by_year_by_profile[pid][int(row["year"])] = int(row["cnt"])
        logger.info(
            "Publication years: %d profile-year rows → %d profiles",
            pub_year_rows,
            len(pubs_by_year_by_profile),
        )

    polon_projects_by_year_by_profile: dict[str, dict[int, int]] = defaultdict(dict)
    if _table_exists(conn, "profile_projects") and _table_exists(conn, "projects"):
        with log_step(logger, "SQL: POLON project counts by start year"):
            project_rows = 0
            for row in conn.execute(
                """
                SELECT pp.profile_id,
                       CAST(substr(p.start_date, 1, 4) AS INTEGER) AS y,
                       COUNT(DISTINCT p.id) AS cnt
                FROM profile_projects pp
                JOIN projects p ON p.id = pp.project_id
                WHERE p.project_source = 'POLON'
                  AND p.start_date IS NOT NULL
                  AND length(p.start_date) >= 4
                GROUP BY pp.profile_id, y
                """
            ):
                project_rows += 1
                pid = str(row["profile_id"])
                if pid in domain_codes:
                    polon_projects_by_year_by_profile[pid][int(row["y"])] = int(row["cnt"])
            logger.info(
                "POLON projects: %d profile-year rows → %d profiles",
                project_rows,
                len(polon_projects_by_year_by_profile),
            )
    else:
        logger.debug("Skipping profile_projects (table missing)")

    keywords_by_profile: dict[str, list[tuple[str, int]]] = defaultdict(list)
    with log_step(logger, "SQL: profile keywords"):
        kw_rows = 0
        for row in conn.execute(
        """
        SELECT pk.profile_id, k.term, pk.count
        FROM profile_keywords pk
        JOIN keywords k ON k.id = pk.keyword_id
        ORDER BY pk.count DESC
        """
        ):
            kw_rows += 1
            pid = str(row["profile_id"])
            if pid in domain_codes:
                keywords_by_profile[pid].append((str(row["term"]), int(row["count"] or 1)))
        logger.info(
            "Keywords: %d rows → %d profiles",
            kw_rows,
            len(keywords_by_profile),
        )

    domains_by_profile: dict[str, list[str]] = defaultdict(list)
    with log_step(logger, "SQL: domains and disciplines"):
        for row in conn.execute(
            """
            SELECT p.id AS profile_id, d.label_pl, d.label_en
            FROM profiles p
            LEFT JOIN scientific_domains d ON d.code = p.domain_code
            WHERE p.is_stub = 0 AND p.domain_code IS NOT NULL
            """
        ):
            pid = str(row["profile_id"])
            label = _label(row["label_pl"], row["label_en"])
            if label:
                domains_by_profile[pid].append(label)

        for row in conn.execute(
            """
            SELECT pdd.profile_id, d.label_pl, d.label_en
            FROM profile_domain_disciplines pdd
            JOIN scientific_domains d ON d.code = pdd.discipline_code
            """
        ):
            pid = str(row["profile_id"])
            if pid not in domain_codes:
                continue
            label = _label(row["label_pl"], row["label_en"])
            if label:
                domains_by_profile[pid].append(label)
        logger.info("Domains/disciplines: %d profiles with labels", len(domains_by_profile))

    specialties_by_profile: dict[str, list[str]] = defaultdict(list)
    with log_step(logger, "SQL: specialties"):
        for row in conn.execute(
            """
            SELECT ps.profile_id, s.label_pl, s.label_en
            FROM profile_specialties ps
            JOIN specialties s ON s.id = ps.specialty_id
            ORDER BY ps.sort_order ASC
            """
        ):
            pid = str(row["profile_id"])
            if pid not in domain_codes:
                continue
            label = _label(row["label_pl"], row["label_en"])
            if label:
                specialties_by_profile[pid].append(label)
        logger.info("Specialties: %d profiles", len(specialties_by_profile))

    institutions_by_profile: dict[str, list[str]] = defaultdict(list)
    if _table_exists(conn, "profile_institutions") and _table_exists(conn, "institutions"):
        with log_step(logger, "SQL: profile_institutions"):
            inst_rows = 0
            for row in conn.execute(
            """
            SELECT pi.profile_id, i.name, pi.ludzie_institution_name
            FROM profile_institutions pi
            JOIN institutions i ON i.id = pi.institution_id
            """
            ):
                inst_rows += 1
                pid = str(row["profile_id"])
                if pid not in domain_codes:
                    continue
                name = _label(row["name"], row["ludzie_institution_name"])
                if name:
                    institutions_by_profile[pid].append(name)
            logger.info("Institutions (RADON): %d rows", inst_rows)
    else:
        logger.debug("Skipping profile_institutions (table missing)")

    if _table_exists(conn, "profile_memberships") and _table_exists(conn, "organizations"):
        with log_step(logger, "SQL: profile_memberships / organizations"):
            for row in conn.execute(
                """
                SELECT pm.profile_id, o.name
                FROM profile_memberships pm
                JOIN organizations o ON o.id = pm.org_id
                """
            ):
                pid = str(row["profile_id"])
                if pid not in domain_codes:
                    continue
                name = _label(row["name"])
                if name:
                    institutions_by_profile[pid].append(name)
            logger.info("Institutions total: %d profiles", len(institutions_by_profile))
    else:
        logger.debug("Skipping profile_memberships (table missing)")

    degree_labels_by_profile: dict[str, list[str]] = defaultdict(list)
    degree_codes = {pid: code for pid, code in degree_codes_by_profile.items() if code}
    if degree_codes and _table_exists(conn, "degree_titles"):
        with log_step(logger, "SQL: degree titles", n_codes=len(set(degree_codes.values()))):
            unique_codes = tuple(set(str(c) for c in degree_codes.values()))
            placeholders = ",".join(["?"] * len(unique_codes))
            code_to_label: dict[str, str] = {}
            for row in conn.execute(
                f"""
                SELECT code, label FROM degree_titles WHERE code IN ({placeholders})
                """,
                unique_codes,
            ):
                label = _label(row["label"])
                if label:
                    code_to_label[str(row["code"])] = label
            for pid, code in degree_codes.items():
                label = code_to_label.get(str(code))
                if label:
                    degree_labels_by_profile[pid].append(label)
            logger.info("Degree labels: %d profiles", len(degree_labels_by_profile))

    about_count = sum(1 for v in about_me_by_profile.values() if v)
    logger.info("About-me text: %d profiles", about_count)

    return _ProfileBundle(
        profile_ids=profile_ids,
        domain_codes=domain_codes,
        degree_codes_by_profile=degree_codes_by_profile,
        titles_by_profile=titles_by_profile,
        pub_stats=pub_stats,
        pubs_by_year_by_profile=dict(pubs_by_year_by_profile),
        polon_projects_by_year_by_profile=dict(polon_projects_by_year_by_profile),
        keywords_by_profile=keywords_by_profile,
        domains_by_profile=domains_by_profile,
        specialties_by_profile=specialties_by_profile,
        institutions_by_profile=institutions_by_profile,
        about_me_by_profile=about_me_by_profile,
        degree_labels_by_profile=degree_labels_by_profile,
    )


def build_scientist_corpus(
    conn: sqlite3.Connection,
    mode: SearchMode = SearchMode.PUBLICATIONS,
) -> list[ScientistDocument]:
    logger = get_build_logger()
    bundle = _load_profile_bundle(conn)
    if bundle is None:
        return []

    with log_step(logger, "Assemble scientist documents", mode=mode.value):
        documents: list[ScientistDocument] = []
        for pid in bundle.profile_ids:
            stats = bundle.pub_stats.get(pid, {"pub_count": 0, "max_year": None})
            if mode == SearchMode.PROFILE:
                text = _assemble_profile_text(
                    bundle.keywords_by_profile.get(pid, []),
                    bundle.domains_by_profile.get(pid, []),
                    bundle.specialties_by_profile.get(pid, []),
                    bundle.institutions_by_profile.get(pid, []),
                    bundle.about_me_by_profile.get(pid, []),
                    bundle.degree_labels_by_profile.get(pid, []),
                )
            else:
                text = _assemble_publications_text(
                    bundle.titles_by_profile.get(pid, []),
                    bundle.keywords_by_profile.get(pid, []),
                    bundle.domains_by_profile.get(pid, []),
                    bundle.specialties_by_profile.get(pid, []),
                )

            documents.append(
                ScientistDocument(
                    profile_id=pid,
                    text=text,
                    meta={
                        "pub_count": stats["pub_count"],
                        "max_year": stats["max_year"],
                        "domain_code": bundle.domain_codes.get(pid),
                        "degree_code": bundle.degree_codes_by_profile.get(pid),
                        "pubs_by_year": bundle.pubs_by_year_by_profile.get(pid, {}),
                        "polon_projects_by_year": bundle.polon_projects_by_year_by_profile.get(
                            pid, {}
                        ),
                        "search_mode": mode.value,
                    },
                    search_mode=mode.value,
                )
            )
    return documents


def save_corpus_jsonl(documents: list[ScientistDocument], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for doc in documents:
            handle.write(
                json.dumps(
                    {
                        "profile_id": doc.profile_id,
                        "text": doc.text,
                        "meta": doc.meta,
                        "search_mode": doc.search_mode,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def load_corpus_jsonl(path: Path) -> list[ScientistDocument]:
    documents: list[ScientistDocument] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            mode = str(payload.get("search_mode") or payload.get("meta", {}).get("search_mode") or "")
            documents.append(
                ScientistDocument(
                    profile_id=str(payload["profile_id"]),
                    text=str(payload.get("text") or ""),
                    meta=dict(payload.get("meta") or {}),
                    search_mode=mode,
                )
            )
    return documents


def profile_id_index(documents: list[ScientistDocument]) -> list[str]:
    return [doc.profile_id for doc in documents]


def save_profile_id_index(profile_ids: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile_ids, ensure_ascii=False, indent=2), encoding="utf-8")


def load_profile_id_index(path: Path) -> list[str]:
    return [str(pid) for pid in json.loads(path.read_text(encoding="utf-8"))]


def profile_id_to_index(profile_ids: list[str]) -> dict[str, int]:
    return {pid: idx for idx, pid in enumerate(profile_ids)}


def legacy_corpus_path(artifacts_dir: Path) -> Path:
    """Pre-dual-mode flat layout."""
    return artifacts_dir / CORPUS_FILENAME


def resolve_mode_dir(artifacts_dir: Path, mode: SearchMode) -> Path:
    """Prefer artifacts_dir/<mode>/; fall back to flat layout for publications only."""
    nested = mode_artifact_dir(artifacts_dir, mode)
    if (nested / CORPUS_FILENAME).is_file():
        return nested
    if mode == SearchMode.PUBLICATIONS and legacy_corpus_path(artifacts_dir).is_file():
        return artifacts_dir
    return nested


_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text or "")]


def iter_tokenized(documents: list[ScientistDocument]) -> Iterator[list[str]]:
    for doc in documents:
        yield tokenize(doc.text)
