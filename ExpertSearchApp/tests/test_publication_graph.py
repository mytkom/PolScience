from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
import unittest


from src import (  # noqa: E402
    build_publication_graph,
    ensure_graph_indexes,
    load_publication_neighborhood_by_shared_authors,
)


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE publications (
            id TEXT PRIMARY KEY,
            title TEXT,
            abstract TEXT,
            year INTEGER,
            doi TEXT,
            journal_name TEXT,
            pages TEXT,
            publication_type TEXT,
            url TEXT,
            detail_fetched INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE profiles (
            id TEXT PRIMARY KEY,
            given_name TEXT,
            is_stub INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE authorship (
            profile_id TEXT NOT NULL REFERENCES profiles (id),
            publication_id TEXT NOT NULL REFERENCES publications (id),
            PRIMARY KEY (profile_id, publication_id)
        );
        """
    )
    return conn


def _seed_shared_authors_fixture(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO publications (id, title, year) VALUES (?, ?, ?)",
        [
            ("p1", "Root paper", 2024),
            ("p2", "Neighbor one", 2023),
            ("p3", "Neighbor two", 2022),
            ("p4", "Isolated paper", 2021),
        ],
    )
    conn.executemany(
        "INSERT INTO profiles (id, given_name, is_stub) VALUES (?, ?, 0)",
        [
            ("a", "Alice"),
            ("b", "Bob"),
            ("c", "Carol"),
            ("d", "Dan"),
        ],
    )
    conn.executemany(
        "INSERT INTO authorship (profile_id, publication_id) VALUES (?, ?)",
        [
            ("a", "p1"),
            ("b", "p1"),
            ("a", "p2"),
            ("b", "p3"),
            ("c", "p3"),
            ("d", "p4"),
        ],
    )


class PublicationGraphTests(unittest.TestCase):
    def test_neighborhood_by_shared_authors_is_root_centered(self) -> None:
        conn = _make_conn()
        try:
            _seed_shared_authors_fixture(conn)

            neighborhood = load_publication_neighborhood_by_shared_authors(conn, publication_id="p1")

            self.assertEqual(neighborhood.root_id, "p1")
            self.assertIsNotNone(neighborhood.root)
            self.assertEqual(set(neighborhood.neighbors), {"p2", "p3"})
            self.assertEqual({(edge.source, edge.target, edge.weight) for edge in neighborhood.edges}, {
                ("p1", "p2", 1.0),
                ("p1", "p3", 1.0),
            })
        finally:
            conn.close()

    def test_build_publication_graph_returns_only_local_subgraph(self) -> None:
        conn = _make_conn()
        try:
            _seed_shared_authors_fixture(conn)

            graph = build_publication_graph(conn, publication_id="p1")

            self.assertEqual(set(graph.nodes), {"p1", "p2", "p3"})
            self.assertEqual(graph.node("p1").label, "Root paper")
            self.assertEqual(set(graph.neighbors("p1")), {"p2", "p3"})
            self.assertNotIn("p4", graph.nodes)
        finally:
            conn.close()

    def test_ensure_graph_indexes_creates_profile_index(self) -> None:
        conn = _make_conn()
        try:
            ensure_graph_indexes(conn)
            rows = conn.execute("PRAGMA index_list('authorship')").fetchall()
            names = {str(row[1]) for row in rows}
            self.assertIn("idx_authorship_profile", names)
        finally:
            conn.close()

    def test_missing_publication_returns_empty_neighborhood(self) -> None:
        conn = _make_conn()
        try:
            neighborhood = load_publication_neighborhood_by_shared_authors(conn, publication_id="missing")

            self.assertIsNone(neighborhood.root)
            self.assertEqual(neighborhood.neighbors, {})
            self.assertEqual(neighborhood.edges, [])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()