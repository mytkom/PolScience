"""Structural filters for expert search (publications, projects, degree, institutions)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

# Lower rank = higher qualification (from Ludzie Nauki degree_titles).
_DEGREE_RANK: dict[str, int] = {
    "PROF": 0,
    "PROF_OF_ART": 0,
    "DR_HAB": 1,
    "DRHAB": 1,
    "DRHAB_OF_ART": 1,
    "DR": 2,
    "DR_OF_ART": 2,
    "LEK": 2,
    "LEKDEN": 2,
    "LEKWET": 2,
    "MGR": 3,
    "MGRINZ": 3,
    "MGRSZT": 3,
    "MGRPIEL": 3,
    "MGRFAR": 3,
    "MGRPOL": 3,
    "MGRINZPOZ": 3,
    "MGRINZARCH": 3,
    "MGRINZARCHKR": 3,
    "INZ": 4,
    "INZARCH": 4,
    "INZARCHKR": 4,
    "LIC": 5,
    "LICPIEL": 5,
    "LICPOL": 5,
    "OD": 6,
}

MGR_RANK_THRESHOLD = 3


def normalize_degree_code(code: str | None) -> str | None:
    if not code:
        return None
    normalized = str(code).strip().upper()
    if normalized == "DRHAB":
        return "DR_HAB"
    return normalized or None


def degree_rank(code: str | None) -> int:
    normalized = normalize_degree_code(code)
    if not normalized:
        return 999
    return _DEGREE_RANK.get(normalized, 99)


def meets_mgr_plus(degree_code: str | None) -> bool:
    """Master's level and above (proxy for PhD student or higher)."""
    return degree_rank(degree_code) <= MGR_RANK_THRESHOLD


def _year_counts(counts_by_year: Mapping[Any, Any] | None) -> dict[int, int]:
    if not counts_by_year:
        return {}
    out: dict[int, int] = {}
    for raw_year, raw_count in counts_by_year.items():
        try:
            year = int(raw_year)
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        if count > 0:
            out[year] = count
    return out


def count_since_year(counts_by_year: Mapping[Any, Any] | None, since_year: int) -> int:
    return sum(count for year, count in _year_counts(counts_by_year).items() if year >= since_year)


def passes_min_count_since(
    counts_by_year: Mapping[Any, Any] | None,
    *,
    min_count: int,
    since_year: int,
) -> bool:
    return count_since_year(counts_by_year, since_year) >= min_count


def _split_institution_tokens(values: list[str] | None) -> list[str]:
    tokens: list[str] = []
    for raw in values or []:
        for part in str(raw).split(","):
            token = part.strip()
            if token:
                tokens.append(token)
    return tokens


def lookup_institution_ids_by_name(db_path: Path, name_query: str) -> list[str]:
    """Case-insensitive substring match on institutions.name."""
    query = name_query.strip()
    if not query:
        return []
    sql = """
        SELECT id
        FROM institutions
        WHERE LOWER(name) LIKE LOWER(?)
        ORDER BY name
    """
    pattern = f"%{query}%"
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        rows = conn.execute(sql, (pattern,)).fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows]


def resolve_institution_filter_ids(
    db_path: Path,
    *,
    institution_ids: list[str] | None = None,
    institution_names: list[str] | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """Merge explicit IDs with IDs resolved from name queries.

    Returns (unique_ids, name_to_ids) where name_to_ids maps each name query to
    matching institution IDs (empty list if none).
    """
    resolved_ids: list[str] = []
    name_to_ids: dict[str, list[str]] = {}
    for inst_id in _split_institution_tokens(institution_ids):
        resolved_ids.append(inst_id)
    for name in _split_institution_tokens(institution_names):
        matches = lookup_institution_ids_by_name(db_path, name)
        name_to_ids[name] = matches
        resolved_ids.extend(matches)
    unique_ids = list(dict.fromkeys(resolved_ids))
    return unique_ids, name_to_ids


def load_profiles_at_institutions(
    db_path: Path,
    institution_ids: list[str],
) -> frozenset[str]:
    """Profiles with CURRENT employment at any of the given institution IDs."""
    unique_ids = [str(i).strip() for i in institution_ids if str(i).strip()]
    if not unique_ids:
        return frozenset()
    placeholders = ",".join(["?"] * len(unique_ids))
    sql = f"""
        SELECT DISTINCT profile_id
        FROM profile_institutions
        WHERE status_employment = 'CURRENT'
          AND institution_id IN ({placeholders})
    """
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        rows = conn.execute(sql, unique_ids).fetchall()
    finally:
        conn.close()
    return frozenset(str(row[0]) for row in rows)


def load_current_institution_names(
    db_path: Path,
    profile_ids: list[str],
) -> dict[str, str]:
    """Comma-separated CURRENT institution names per profile."""
    unique_ids = list(dict.fromkeys(profile_ids))
    if not unique_ids:
        return {}
    placeholders = ",".join(["?"] * len(unique_ids))
    sql = f"""
        SELECT pi.profile_id,
               COALESCE(NULLIF(TRIM(i.name), ''), NULLIF(TRIM(pi.ludzie_institution_name), '')) AS name
        FROM profile_institutions pi
        LEFT JOIN institutions i ON i.id = pi.institution_id
        WHERE pi.status_employment = 'CURRENT'
          AND pi.profile_id IN ({placeholders})
        ORDER BY name
    """
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        rows = conn.execute(sql, unique_ids).fetchall()
    finally:
        conn.close()
    names_by_profile: dict[str, list[str]] = {}
    for profile_id, name in rows:
        if not name:
            continue
        pid = str(profile_id)
        label = str(name).strip()
        if not label:
            continue
        bucket = names_by_profile.setdefault(pid, [])
        if label not in bucket:
            bucket.append(label)
    return {pid: ", ".join(names) for pid, names in names_by_profile.items()}


def load_degree_labels(db_path: Path, profile_ids: list[str]) -> dict[str, str]:
    unique_ids = list(dict.fromkeys(profile_ids))
    if not unique_ids:
        return {}
    placeholders = ",".join(["?"] * len(unique_ids))
    sql = f"""
        SELECT p.id, COALESCE(NULLIF(TRIM(dt.label), ''), NULLIF(TRIM(p.degree_code), '')) AS degree
        FROM profiles p
        LEFT JOIN degree_titles dt ON dt.code = p.degree_code
        WHERE p.id IN ({placeholders})
    """
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        rows = conn.execute(sql, unique_ids).fetchall()
    finally:
        conn.close()
    out: dict[str, str] = {}
    for profile_id, degree in rows:
        if degree:
            out[str(profile_id)] = str(degree).strip()
    return out


def passes_structural_filters(
    meta: dict[str, Any],
    *,
    min_pubs: int | None = None,
    domain_code: str | None = None,
    min_year: int | None = None,
    min_pubs_since: int | None = None,
    since_year: int | None = None,
    min_polon_projects: int | None = None,
    projects_since_year: int | None = None,
    require_mgr_plus: bool = False,
    institution_eligible: frozenset[str] | None = None,
    profile_id: str | None = None,
) -> bool:
    if min_pubs is not None and int(meta.get("pub_count") or 0) < min_pubs:
        return False
    if domain_code is not None:
        if str(meta.get("domain_code") or "") != domain_code:
            return False
    if min_year is not None:
        max_year = meta.get("max_year")
        if max_year is None or int(max_year) < min_year:
            return False
    if min_pubs_since is not None and since_year is not None:
        if not passes_min_count_since(
            meta.get("pubs_by_year"),
            min_count=min_pubs_since,
            since_year=since_year,
        ):
            return False
    if min_polon_projects is not None and projects_since_year is not None:
        if not passes_min_count_since(
            meta.get("polon_projects_by_year"),
            min_count=min_polon_projects,
            since_year=projects_since_year,
        ):
            return False
    if require_mgr_plus and not meets_mgr_plus(meta.get("degree_code")):
        return False
    if institution_eligible is not None and profile_id is not None:
        if profile_id not in institution_eligible:
            return False
    return True
