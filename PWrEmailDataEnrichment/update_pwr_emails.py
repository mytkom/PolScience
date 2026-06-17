#!/usr/bin/env python3
"""Update profile emails in SQLite DB from PWr people.json by name match."""

from __future__ import annotations

import argparse
import json
import sqlite3
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def normalize_text(value: str) -> str:
    """Normalize text for resilient matching."""
    stripped = value.strip().casefold()
    decomposed = unicodedata.normalize("NFKD", stripped)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def split_full_name(full_name: str) -> Tuple[str, str] | None:
    """Split full name into (given_name, surname)."""
    parts = full_name.strip().split()
    if len(parts) < 2:
        return None
    given_name = parts[0]
    surname = " ".join(parts[1:])
    return given_name, surname


def ensure_email_column(conn: sqlite3.Connection) -> None:
    """Add email column to profiles if missing."""
    rows = conn.execute("PRAGMA table_info(profiles)").fetchall()
    columns = {row[1] for row in rows}
    if "email" not in columns:
        conn.execute("ALTER TABLE profiles ADD COLUMN email TEXT")


def load_people_emails(json_path: Path) -> Tuple[Dict[Tuple[str, str], str], int]:
    """Load unique (given_name, surname) -> email mapping."""
    with json_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    people_list = payload.get("extracted_extractlist_5jc9")
    if not isinstance(people_list, list):
        raise ValueError("Expected key 'extracted_extractlist_5jc9' with a list.")

    by_name: Dict[Tuple[str, str], str] = {}
    ambiguous_keys = set()

    for entry in people_list:
        if not isinstance(entry, dict):
            continue
        full_name = str(entry.get("name", "")).strip()
        email = str(entry.get("email", "")).strip()
        if not full_name or not email:
            continue

        split_name = split_full_name(full_name)
        if split_name is None:
            continue

        key = (normalize_text(split_name[0]), normalize_text(split_name[1]))
        existing_email = by_name.get(key)
        if existing_email is None:
            by_name[key] = email
        elif existing_email != email:
            ambiguous_keys.add(key)

    for key in ambiguous_keys:
        by_name.pop(key, None)

    return by_name, len(ambiguous_keys)


def fetch_profiles(
    conn: sqlite3.Connection,
) -> List[Tuple[str, str, str]]:
    """Fetch profiles linked to Politechnika Wroclawska institutions."""
    rows = conn.execute(
        """
        SELECT id, given_name, surname
        FROM profiles
        WHERE given_name IS NOT NULL
          AND surname IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM profile_institutions pi
              JOIN institutions i ON i.id = pi.institution_id
              WHERE pi.profile_id = profiles.id
                AND (
                    lower(i.name) LIKE '%politechnika wroclawska%'
                    OR lower(i.name) LIKE '%politechnika wrocławska%'
                )
          )
        """
    ).fetchall()
    return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]


def index_profiles(
    profiles: Iterable[Tuple[str, str, str]]
) -> Dict[Tuple[str, str], List[str]]:
    """Build map of normalized name key -> profile ids."""
    indexed: Dict[Tuple[str, str], List[str]] = {}
    for profile_id, given_name, surname in profiles:
        key = (normalize_text(given_name), normalize_text(surname))
        indexed.setdefault(key, []).append(profile_id)
    return indexed


def update_emails(db_path: Path, people_json_path: Path) -> None:
    """Run matching and update emails in SQLite."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")
    if not people_json_path.exists():
        raise FileNotFoundError(f"people.json not found: {people_json_path}")

    with sqlite3.connect(db_path) as conn:
        ensure_email_column(conn)

        people_emails, ambiguous_people_keys = load_people_emails(people_json_path)
        profiles = fetch_profiles(conn)
        profiles_by_name = index_profiles(profiles)

        updates: List[Tuple[str, str]] = []
        unmatched_in_db = 0
        one_to_many_matches = 0

        for name_key, email in people_emails.items():
            profile_ids = profiles_by_name.get(name_key)
            if not profile_ids:
                unmatched_in_db += 1
                continue
            if len(profile_ids) > 1:
                one_to_many_matches += 1
            for profile_id in profile_ids:
                updates.append((email, profile_id))

        conn.executemany("UPDATE profiles SET email = ? WHERE id = ?", updates)
        conn.commit()

    print(f"People entries with unique email key: {len(people_emails)}")
    print(f"Ambiguous people keys skipped: {ambiguous_people_keys}")
    print(f"Unmatched keys in DB: {unmatched_in_db}")
    print(f"One-to-many DB key matches: {one_to_many_matches}")
    print(f"Profiles updated: {len(updates)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Match PWr people by first name + surname and update profiles.email "
            "in SQLite database."
        )
    )
    parser.add_argument("sqlite_db", type=Path, help="Path to SQLite database file")
    parser.add_argument(
        "--people-json",
        type=Path,
        default=Path(__file__).with_name("people.json"),
        help="Path to people.json (default: PWrEmailData/people.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    update_emails(db_path=args.sqlite_db, people_json_path=args.people_json)


if __name__ == "__main__":
    main()
