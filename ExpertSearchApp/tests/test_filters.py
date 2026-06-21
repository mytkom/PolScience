from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.retrieval.filters import (  # noqa: E402
    count_since_year,
    load_current_institution_names,
    load_degree_labels,
    load_profiles_at_institutions,
    lookup_institution_ids_by_name,
    meets_mgr_plus,
    passes_min_count_since,
    passes_structural_filters,
    resolve_institution_filter_ids,
)


class TestFilters(unittest.TestCase):
    def test_count_since_year(self) -> None:
        counts = {2018: 2, 2019: 1, 2021: 3}
        self.assertEqual(count_since_year(counts, 2020), 3)
        self.assertEqual(count_since_year(counts, 2019), 4)
        self.assertEqual(count_since_year({}, 2020), 0)

    def test_passes_min_count_since(self) -> None:
        counts = {"2020": 2, "2021": 1}
        self.assertTrue(passes_min_count_since(counts, min_count=2, since_year=2020))
        self.assertFalse(passes_min_count_since(counts, min_count=4, since_year=2020))

    def test_meets_mgr_plus(self) -> None:
        self.assertTrue(meets_mgr_plus("MGR"))
        self.assertTrue(meets_mgr_plus("DR"))
        self.assertTrue(meets_mgr_plus("MGRINZ"))
        self.assertFalse(meets_mgr_plus("LIC"))
        self.assertFalse(meets_mgr_plus("INZ"))
        self.assertFalse(meets_mgr_plus(None))

    def test_passes_structural_filters_combined(self) -> None:
        meta = {
            "pub_count": 10,
            "degree_code": "DR",
            "pubs_by_year": {2020: 1, 2022: 2},
            "polon_projects_by_year": {2021: 1},
        }
        self.assertTrue(
            passes_structural_filters(
                meta,
                min_pubs_since=2,
                since_year=2020,
                min_polon_projects=1,
                projects_since_year=2020,
                require_mgr_plus=True,
                profile_id="alice",
                institution_eligible=frozenset({"alice"}),
            )
        )
        self.assertFalse(
            passes_structural_filters(
                meta,
                require_mgr_plus=True,
                profile_id="alice",
                institution_eligible=frozenset({"bob"}),
            )
        )

    def test_load_profiles_at_institutions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE profile_institutions (
                    employment_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    institution_id TEXT NOT NULL,
                    status_employment TEXT
                );
                INSERT INTO profile_institutions VALUES
                    ('e1', 'alice', 'uw', 'CURRENT'),
                    ('e2', 'bob', 'uw', 'ARCHIVE'),
                    ('e3', 'carol', 'agh', 'CURRENT');
                """
            )
            conn.commit()
            conn.close()

            eligible = load_profiles_at_institutions(db_path, ["uw"])
            self.assertEqual(eligible, frozenset({"alice"}))

    def test_lookup_institution_ids_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE institutions (id TEXT PRIMARY KEY, name TEXT NOT NULL);
                INSERT INTO institutions VALUES
                    ('uw', 'Uniwersytet Warszawski'),
                    ('agh', 'Akademia Górniczo-Hutnicza');
                """
            )
            conn.commit()
            conn.close()

            self.assertEqual(
                lookup_institution_ids_by_name(db_path, "warszawski"),
                ["uw"],
            )
            self.assertEqual(lookup_institution_ids_by_name(db_path, "missing"), [])

    def test_resolve_institution_filter_ids_merges_ids_and_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE institutions (id TEXT PRIMARY KEY, name TEXT NOT NULL);
                INSERT INTO institutions VALUES ('uw', 'Uniwersytet Warszawski');
                """
            )
            conn.commit()
            conn.close()

            ids, name_map = resolve_institution_filter_ids(
                db_path,
                institution_ids=["agh"],
                institution_names=["Warszawski"],
            )
            self.assertEqual(ids, ["agh", "uw"])
            self.assertEqual(name_map, {"Warszawski": ["uw"]})

    def test_load_current_institution_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE institutions (id TEXT PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE profile_institutions (
                    employment_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    institution_id TEXT NOT NULL,
                    status_employment TEXT,
                    ludzie_institution_name TEXT
                );
                INSERT INTO institutions VALUES ('uw', 'Uniwersytet Warszawski');
                INSERT INTO profile_institutions VALUES
                    ('e1', 'alice', 'uw', 'CURRENT', NULL),
                    ('e2', 'alice', 'uw', 'ARCHIVE', NULL),
                    ('e3', 'bob', 'uw', 'CURRENT', 'Fallback Name');
                """
            )
            conn.commit()
            conn.close()

            names = load_current_institution_names(db_path, ["alice", "bob"])
            self.assertEqual(names["alice"], "Uniwersytet Warszawski")
            self.assertEqual(names["bob"], "Uniwersytet Warszawski")

    def test_load_degree_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE degree_titles (code TEXT PRIMARY KEY, label TEXT NOT NULL);
                CREATE TABLE profiles (id TEXT PRIMARY KEY, degree_code TEXT);
                INSERT INTO degree_titles VALUES ('DR', 'doktor');
                INSERT INTO profiles VALUES ('alice', 'DR');
                """
            )
            conn.commit()
            conn.close()

            self.assertEqual(load_degree_labels(db_path, ["alice"]), {"alice": "doktor"})


if __name__ == "__main__":
    unittest.main()
