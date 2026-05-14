#!/usr/bin/env python3
"""Add institutions.student_count and fill from institution_counts.csv (default: 2024 column).

CSV is comma-separated; names containing commas appear quoted — handled by csv.reader.

Example:
  python scripts/add_institution_student_counts.py --db ./data.sqlite
  python scripts/add_institution_student_counts.py --db ./data.sqlite --csv ./my_counts.csv --year 2023
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path


def _ensure_student_count_column(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(institutions)")}
    if "student_count" not in cols:
        conn.execute("ALTER TABLE institutions ADD COLUMN student_count INTEGER")


def _parse_count(raw: str | None) -> int | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return int(s)


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    default_csv = repo_root / "institution_counts.csv"

    p = argparse.ArgumentParser(description="Fill institutions.student_count from CSV")
    p.add_argument("--db", required=True, type=Path, help="SQLite database path")
    p.add_argument(
        "--csv",
        type=Path,
        default=default_csv,
        help=f"CSV path (default: {default_csv})",
    )
    p.add_argument(
        "--year",
        default="2024",
        help="Column header for student counts (default: 2024)",
    )
    ns = p.parse_args(argv)

    db_path = ns.db.expanduser().resolve()
    csv_path = ns.csv.expanduser().resolve()
    year_col = str(ns.year).strip()

    if not db_path.is_file():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return 2
    if not csv_path.is_file():
        print(f"error: CSV not found: {csv_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _ensure_student_count_column(conn)

        updated = 0
        skipped_empty = 0
        missing_institution = 0
        csv_rows = 0

        with csv_path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                print("error: CSV has no header row", file=sys.stderr)
                return 3
            if "id" not in reader.fieldnames:
                print(f"error: CSV missing 'id' column (have {reader.fieldnames})", file=sys.stderr)
                return 3
            if year_col not in reader.fieldnames:
                print(
                    f"error: CSV missing year column {year_col!r} (have {reader.fieldnames})",
                    file=sys.stderr,
                )
                return 3

            for row in reader:
                csv_rows += 1
                iid = (row.get("id") or "").strip()
                if not iid:
                    continue
                cnt = _parse_count(row.get(year_col))
                if cnt is None:
                    skipped_empty += 1
                    continue

                cur = conn.execute(
                    "UPDATE institutions SET student_count = ? WHERE id = ?", (cnt, iid)
                )
                if cur.rowcount == 0:
                    missing_institution += 1
                else:
                    updated += 1

        conn.commit()
        print(
            f"CSV rows read: {csv_rows}; institutions updated ({year_col}): {updated}; "
            f"skipped empty {year_col}: {skipped_empty}; CSV id not in DB: {missing_institution}"
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
