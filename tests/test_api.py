from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from src.api.app import app  # noqa: E402
from src.api.config import ApiSettings  # noqa: E402
from src.api.schemas import FusionWeightsApplied  # noqa: E402
from src.api.search_service import CSV_COLUMNS, search_response_to_csv  # noqa: E402
from src.retrieval.pipeline import QueryResult  # noqa: E402


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE profiles (
            id TEXT PRIMARY KEY,
            prefix TEXT,
            given_name TEXT,
            second_name TEXT,
            surname TEXT,
            is_stub INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO profiles (id, prefix, given_name, second_name, surname, is_stub)
        VALUES ('alice', 'dr', 'Anna', NULL, 'Nowak', 0),
               ('bob', NULL, 'Boris', 'J.', 'Kowalski', 0)
        """
    )
    conn.commit()
    conn.close()


class TestApi(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.db_path = root / "test.sqlite"
        self.artifacts_dir = root / "artifacts"
        self.artifacts_dir.mkdir()
        _make_db(self.db_path)
        self.settings = ApiSettings(
            db_path=self.db_path,
            artifacts_dir=self.artifacts_dir,
            eager_load=False,
        )
        self.preload_model_patcher = patch(
            "src.api.app.preload_embedding_model",
            autospec=True,
        )
        self.preload_indexes_patcher = patch(
            "src.api.app.preload_search_indexes",
            autospec=True,
        )
        self.preload_model_patcher.start()
        self.preload_indexes_patcher.start()
        self.client = TestClient(app)
        app.state.settings = self.settings

    def tearDown(self) -> None:
        self.preload_model_patcher.stop()
        self.preload_indexes_patcher.stop()
        self._tmpdir.cleanup()

    def test_health_reports_paths(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["db"])
        self.assertTrue(payload["artifacts"])

    def test_csv_export_utf8_bom_for_polish_names(self) -> None:
        from src.api.schemas import ExpertResult, SearchResponse

        body = search_response_to_csv(
            SearchResponse(
                query="test",
                search_mode="profile",
                count=1,
                weights=FusionWeightsApplied(
                    keywords=0.25,
                    semantic=0.55,
                    community=0.2,
                ),
                results=[
                    ExpertResult(
                        rank=1,
                        profile_id="asAuFf5p7Vd",
                        name="Michal Roch Żochowski",
                        email="",
                        profile_url="https://example.test/p",
                        final=0.99,
                        bm25=1.0,
                        cosine=0.8,
                        ppr=0.1,
                    ),
                ],
            )
        )
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        self.assertIn("Żochowski".encode("utf-8"), body)

    def test_search_requires_query(self) -> None:
        response = self.client.get("/api/search", params={"q": "  "})
        self.assertEqual(response.status_code, 400)

    @patch("src.api.search_service.query_experts")
    def test_search_json_enriched(self, mock_query: unittest.mock.MagicMock) -> None:
        mock_query.return_value = [
            QueryResult(
                profile_id="alice",
                rank=1,
                final=0.9,
                bm25=0.8,
                cosine=0.7,
                ppr=0.6,
                search_mode="profile",
            ),
            QueryResult(
                profile_id="bob",
                rank=2,
                final=0.5,
                bm25=0.4,
                cosine=0.3,
                ppr=0.2,
                search_mode="profile",
            ),
        ]

        response = self.client.get(
            "/api/search",
            params={
                "q": "biology",
                "mode": "profile",
                "top": 10,
                "w_bm25": 0.5,
                "w_embed": 0.5,
                "w_ppr": 0,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertAlmostEqual(payload["weights"]["keywords"], 0.5)
        self.assertAlmostEqual(payload["weights"]["semantic"], 0.5)
        self.assertAlmostEqual(payload["weights"]["community"], 0.0)
        self.assertEqual(payload["results"][0]["name"], "dr Anna Nowak")
        self.assertEqual(
            payload["results"][0]["profile_url"],
            "https://ludzie.nauka.gov.pl/ln/profiles/anna.nowak.alice",
        )
        self.assertEqual(payload["results"][0]["email"], "")
        mock_query.assert_called_once()

    @patch("src.api.search_service.query_experts")
    def test_search_export_csv(self, mock_query: unittest.mock.MagicMock) -> None:
        mock_query.return_value = [
            QueryResult(
                profile_id="bob",
                rank=1,
                final=1.0,
                bm25=1.0,
                cosine=1.0,
                ppr=1.0,
                search_mode="publications",
            ),
        ]
        response = self.client.get(
            "/api/search/export.csv",
            params={"q": "test", "mode": "publications"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers.get("content-type", ""))
        self.assertIn("attachment", response.headers.get("content-disposition", ""))
        raw = response.content
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8-sig")
        lines = text.strip().splitlines()
        self.assertEqual(lines[0], ",".join(CSV_COLUMNS))
        self.assertIn("bob", lines[1])

    def test_index_html(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Expert search", response.text)


if __name__ == "__main__":
    unittest.main()
