"""Load display fields for scientist profiles from SQLite."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.api.profile_urls import build_ludzie_profile_url


@dataclass(frozen=True, slots=True)
class ProfileDisplay:
    profile_id: str
    name: str
    email: str
    profile_url: str


def _format_name(
    prefix: str | None,
    given_name: str | None,
    second_name: str | None,
    surname: str | None,
) -> str:
    parts = [prefix, given_name, second_name, surname]
    name = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return name or "Unknown"


def load_profile_displays(
    db_path: Path,
    profile_ids: list[str],
) -> dict[str, ProfileDisplay]:
    if not profile_ids:
        return {}

    unique_ids = list(dict.fromkeys(profile_ids))
    placeholders = ",".join(["?"] * len(unique_ids))
    sql = f"""
        SELECT id, prefix, given_name, second_name, surname
        FROM profiles
        WHERE id IN ({placeholders})
    """

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(sql, unique_ids).fetchall()
    finally:
        conn.close()

    by_id: dict[str, ProfileDisplay] = {}
    for row in rows:
        pid = str(row[0])
        by_id[pid] = ProfileDisplay(
            profile_id=pid,
            name=_format_name(row[1], row[2], row[3], row[4]),
            email="",
            profile_url=build_ludzie_profile_url(
                pid,
                given_name=row[2],
                surname=row[4],
            ),
        )

    for pid in unique_ids:
        if pid not in by_id:
            by_id[pid] = ProfileDisplay(
                profile_id=pid,
                name="Unknown",
                email="",
                profile_url=build_ludzie_profile_url(pid),
            )
    return by_id
