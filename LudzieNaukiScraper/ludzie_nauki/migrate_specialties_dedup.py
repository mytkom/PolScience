"""One-shot SQLite migration: merge duplicate specialties by normalized PL/EN label sig (union-find).

Usage:
  python -m ludzie_nauki.migrate_specialties_dedup /path/to.sqlite

Always backup DB first (.backup ...).
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from ludzie_nauki.specialty_labels import specialty_sig_en, specialty_sig_pl

LOG = logging.getLogger(__name__)


def _ensure_aliases_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS specialty_aliases (
            ludzie_specialty_id TEXT PRIMARY KEY,
            canonical_specialty_id TEXT NOT NULL REFERENCES specialties (id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_specialty_aliases_canonical ON specialty_aliases (canonical_specialty_id);
        """
    )


class _UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if ra < rb:
            self.parent[rb] = ra
        else:
            self.parent[ra] = rb


def _pick_longest(labels: List[Tuple[str | None, str | None]]) -> Tuple[str | None, str | None]:
    best_pl: str | None = None
    best_en: str | None = None
    for lp, le in labels:
        slp = (lp or "").strip()
        sle = (le or "").strip()
        if slp:
            if best_pl is None or len(slp) >= len(best_pl):
                best_pl = slp
        if sle:
            if best_en is None or len(sle) >= len(best_en):
                best_en = sle
    return best_pl, best_en


def migrate(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT id, label_pl, label_en FROM specialties").fetchall()
    if not rows:
        LOG.info("no specialties rows; nothing to do")
        return {"specialties_before": 0, "components_merged": 0, "losers_deleted": 0}

    ids = [str(r["id"]) for r in rows]
    meta: Dict[str, Tuple[str | None, str | None]] = {
        str(r["id"]): (r["label_pl"], r["label_en"]) for r in rows
    }

    uf = _UnionFind()
    pl_bucket: defaultdict[str, List[str]] = defaultdict(list)
    en_bucket: defaultdict[str, List[str]] = defaultdict(list)

    for sid in ids:
        lp, le = meta[sid]
        spl = specialty_sig_pl(lp)
        if spl:
            pl_bucket[spl].append(sid)
        sen = specialty_sig_en(le)
        if sen:
            en_bucket[sen].append(sid)

    def union_bucket(members: List[str]) -> None:
        u = sorted(set(members))
        if len(u) < 2:
            return
        for i in range(len(u) - 1):
            uf.union(u[i], u[i + 1])

    for members in pl_bucket.values():
        union_bucket(members)
    for members in en_bucket.values():
        union_bucket(members)

    comps: defaultdict[str, List[str]] = defaultdict(list)
    for sid in ids:
        comps[uf.find(sid)].append(sid)

    merged_components = 0
    losers_deleted = 0

    with conn:
        for _, members in comps.items():
            keeper = min(members)
            losers = sorted([x for x in members if x != keeper])
            if not losers:
                continue
            merged_components += 1

            lbl_rows = [meta[x] for x in members]
            best_pl, best_en = _pick_longest(lbl_rows)
            conn.execute(
                "UPDATE specialties SET label_pl = ?, label_en = ? WHERE id = ?",
                (best_pl, best_en, keeper),
            )

            for loser in losers:
                conn.execute(
                    """
                    DELETE FROM profile_specialties
                    WHERE specialty_id = ?
                      AND profile_id IN (
                          SELECT profile_id FROM profile_specialties WHERE specialty_id = ?
                      )
                    """,
                    (loser, keeper),
                )
                conn.execute(
                    "UPDATE profile_specialties SET specialty_id = ? WHERE specialty_id = ?",
                    (keeper, loser),
                )
                conn.execute(
                    """
                    UPDATE specialty_aliases SET canonical_specialty_id = ?
                    WHERE canonical_specialty_id = ?
                    """,
                    (keeper, loser),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO specialty_aliases (ludzie_specialty_id, canonical_specialty_id)
                    VALUES (?, ?)
                    """,
                    (loser, keeper),
                )
                conn.execute("DELETE FROM specialties WHERE id = ?", (loser,))
                losers_deleted += 1

        conn.execute(
            """
            DELETE FROM profile_specialties
            WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM profile_specialties GROUP BY profile_id, specialty_id
            )
            """
        )

    return {
        "specialties_before": len(ids),
        "components_merged": merged_components,
        "losers_deleted": losers_deleted,
    }


def main(argv: List[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Dedupe specialties table + remap profile_specialties")
    p.add_argument("sqlite_db", type=Path, help="Path to SQLite database")
    ns = p.parse_args(argv)
    db_path = ns.sqlite_db.expanduser().resolve()
    if not db_path.is_file():
        LOG.error("not a file: %s", db_path)
        return 2

    conn = sqlite3.connect(str(db_path), isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        _ensure_aliases_table(conn)
        stats = migrate(conn)
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            LOG.error("foreign_key_check failed: %s rows", len(bad))
            return 3
        LOG.info(
            "done specialties_before=%s components_merged=%s loser_rows_deleted=%s",
            stats["specialties_before"],
            stats["components_merged"],
            stats["losers_deleted"],
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
