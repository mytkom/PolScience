from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy import sparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.retrieval.bm25_index import build_bm25_index  # noqa: E402
from src.retrieval.corpus import build_scientist_corpus, tokenize  # noqa: E402
from src.retrieval.modes import SearchMode  # noqa: E402
from src.retrieval.fusion import FusionWeights, fuse_scores  # noqa: E402
from src.retrieval.ppr import personalized_pagerank, seeds_from_bm25_hits  # noqa: E402


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE profiles (
            id TEXT PRIMARY KEY,
            domain_code TEXT,
            is_stub INTEGER NOT NULL DEFAULT 0,
            about_me_pl TEXT,
            about_me_en TEXT,
            degree_code TEXT
        );

        CREATE TABLE publications (
            id TEXT PRIMARY KEY,
            title TEXT,
            year INTEGER
        );

        CREATE TABLE authorship (
            profile_id TEXT NOT NULL,
            publication_id TEXT NOT NULL,
            PRIMARY KEY (profile_id, publication_id)
        );

        CREATE TABLE keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL
        );

        CREATE TABLE profile_keywords (
            profile_id TEXT NOT NULL,
            keyword_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (profile_id, keyword_id, source)
        );

        CREATE TABLE scientific_domains (
            code TEXT PRIMARY KEY,
            label_en TEXT,
            label_pl TEXT
        );

        CREATE TABLE profile_domain_disciplines (
            profile_id TEXT NOT NULL,
            domain_code TEXT NOT NULL,
            discipline_code TEXT NOT NULL,
            PRIMARY KEY (profile_id, discipline_code)
        );

        CREATE TABLE specialties (
            id TEXT PRIMARY KEY,
            label_pl TEXT,
            label_en TEXT
        );

        CREATE TABLE profile_specialties (
            profile_id TEXT NOT NULL,
            specialty_id TEXT NOT NULL,
            sort_order INTEGER,
            PRIMARY KEY (profile_id, specialty_id)
        );
        """
    )
    return conn


class TestRetrievalFusion(unittest.TestCase):
    def test_corpus_includes_titles_and_keywords(self) -> None:
        conn = _make_conn()
        conn.execute("INSERT INTO profiles (id, is_stub) VALUES ('a', 0), ('b', 1)")
        conn.execute("INSERT INTO publications (id, title, year) VALUES ('p1', 'Quantum Error Correction', 2024)")
        conn.execute(
            "INSERT INTO authorship (profile_id, publication_id) VALUES ('a', 'p1')"
        )
        conn.execute("INSERT INTO keywords (id, term) VALUES (1, 'quantum computing')")
        conn.execute(
            """
            INSERT INTO profile_keywords (profile_id, keyword_id, source, count)
            VALUES ('a', 1, 'summary', 2)
            """
        )
        conn.commit()

        pub_docs = build_scientist_corpus(conn, mode=SearchMode.PUBLICATIONS)
        self.assertEqual(len(pub_docs), 1)
        self.assertEqual(pub_docs[0].profile_id, "a")
        self.assertIn("Quantum Error Correction", pub_docs[0].text)
        self.assertIn("quantum computing", pub_docs[0].text)
        self.assertEqual(pub_docs[0].meta["pub_count"], 1)

        profile_docs = build_scientist_corpus(conn, mode=SearchMode.PROFILE)
        self.assertEqual(profile_docs[0].profile_id, "a")
        self.assertNotIn("Quantum Error Correction", profile_docs[0].text)
        self.assertIn("quantum computing", profile_docs[0].text)

    def test_profile_mode_matches_specialty_not_title(self) -> None:
        from src.retrieval.corpus import ScientistDocument

        documents = [
            ScientistDocument(
                profile_id="alice",
                text="biologia molekularna biologia molekularna genetyka",
                meta={},
            ),
            ScientistDocument(
                profile_id="bob",
                text="medieval pottery archaeology",
                meta={},
            ),
        ]
        index = build_bm25_index(documents)
        hits = index.search("biologia molekularna", top_k=2)
        self.assertEqual(hits[0][0], "alice")

    def test_bm25_ranks_keyword_match(self) -> None:
        from src.retrieval.corpus import ScientistDocument

        documents = [
            ScientistDocument(profile_id="alice", text="quantum error correction codes", meta={}),
            ScientistDocument(profile_id="bob", text="medieval pottery archaeology", meta={}),
        ]
        index = build_bm25_index(documents)
        hits = index.search("quantum error correction", top_k=2)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0][0], "alice")
        self.assertEqual(hits[1][0], "bob")
        self.assertGreaterEqual(hits[0][1], hits[1][1])

    def test_fusion_prefers_high_embed_when_weighted(self) -> None:
        candidates = ["a", "b"]
        fused = fuse_scores(
            candidates,
            bm25_scores={"a": 1.0, "b": 1.0},
            embed_scores={"a": 0.1, "b": 0.9},
            ppr_scores={"a": 0.5, "b": 0.5},
            weights=FusionWeights(bm25=0.0, embed=1.0, ppr=0.0),
        )
        self.assertEqual(fused[0][0], "b")

    def test_ppr_boosts_neighbor_of_seed(self) -> None:
        # Chain: seed(0) -- 1 -- 2, isolated 3
        row = np.array([0, 1, 1, 2, 2, 3])
        col = np.array([1, 0, 2, 1, 3, 2])
        data = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        adjacency = sparse.csr_matrix((data, (row, col)), shape=(4, 4))
        rank = personalized_pagerank(adjacency, {0: 1.0}, alpha=0.85)
        self.assertGreater(rank[1], rank[3])
        self.assertGreater(rank[2], rank[3])

    def test_seeds_from_bm25_hits(self) -> None:
        id_to_idx = {"a": 0, "b": 1}
        seeds = seeds_from_bm25_hits([("a", 3.0), ("b", 1.0)], id_to_idx, seed_k=2)
        self.assertEqual(seeds[0], 3.0)
        self.assertEqual(seeds[1], 1.0)

    def test_tokenize_lowercases(self) -> None:
        self.assertEqual(tokenize("Quantum-Computing 101"), ["quantum", "computing", "101"])

if __name__ == "__main__":
    unittest.main()
