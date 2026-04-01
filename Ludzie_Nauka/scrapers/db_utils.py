from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


DB_NAME = "ludzie_nauka.sqlite3"


def get_db_path() -> Path:
    return Path(__file__).parent / DB_NAME


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, indent=2)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def fetch_one_dict(conn: sqlite3.Connection, query: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    cur = conn.execute(query, tuple(params))
    row = cur.fetchone()
    return row_to_dict(row) if row else None


def fetch_all_dicts(conn: sqlite3.Connection, query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cur = conn.execute(query, tuple(params))
    return [row_to_dict(row) for row in cur.fetchall()]