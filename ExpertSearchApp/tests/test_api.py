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
from src.api.search_service import CSV_COLUMNS, csv_columns_for_response, search_response_to_csv  # noqa: E402
from src.api.schemas import FilterColumnsApplied  # noqa: E402
from src.retrieval.graph_metrics import GraphMetricsStore, ResearcherGraphMetrics, clear_graph_metrics_cache  # noqa: E402
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
        self.graphs_dir = root / "graphs"
        self.artifacts_dir.mkdir()
        self.graphs_dir.mkdir()
        _make_db(self.db_path)
        self.settings = ApiSettings(
            db_path=self.db_path,
            artifacts_dir=self.artifacts_dir,
            graphs_dir=self.graphs_dir,
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
        self.preload_graphs_patcher = patch(
            "src.api.app.preload_graph_metrics",
            autospec=True,
        )
        self.preload_model_patcher.start()
        self.preload_indexes_patcher.start()
        self.preload_graphs_patcher.start()
        clear_graph_metrics_cache()
        self.client = TestClient(app)
        app.state.settings = self.settings

    def tearDown(self) -> None:
        self.preload_model_patcher.stop()
        self.preload_indexes_patcher.stop()
        self.preload_graphs_patcher.stop()
        clear_graph_metrics_cache()
        self._tmpdir.cleanup()

    def test_health_reports_paths(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["db"])
        self.assertTrue(payload["artifacts"])
        self.assertFalse(payload["graphs"])
        self.assertIn("graphs_dir", payload)

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

    def test_csv_columns_include_filter_fields(self) -> None:
        from src.api.schemas import ExpertResult, SearchResponse

        response = SearchResponse(
            query="test",
            search_mode="profile",
            count=1,
            weights=FusionWeightsApplied(keywords=0.25, semantic=0.55, community=0.2),
            filter_columns=FilterColumnsApplied(
                pubs_since_year=2020,
                projects_since_year=2021,
                institutions=True,
                degree=True,
            ),
            results=[
                ExpertResult(
                    rank=1,
                    profile_id="alice",
                    name="Anna",
                    email="",
                    profile_url="https://example.test/p",
                    final=0.9,
                    bm25=0.8,
                    cosine=0.7,
                    ppr=0.6,
                    pubs_since_year=3,
                    projects_since_year=1,
                    institutions="Uni A, Uni B",
                    degree="doktor",
                ),
            ],
        )
        columns = csv_columns_for_response(response)
        self.assertEqual(
            columns,
            [
                *CSV_COLUMNS,
                "pubs_since_2020",
                "projects_since_2021",
                "institutions",
                "degree",
            ],
        )
        body = search_response_to_csv(response).decode("utf-8-sig")
        self.assertIn("pubs_since_2020", body.splitlines()[0])
        self.assertIn("Uni A, Uni B", body)
        self.assertIn("doktor", body)

    def test_csv_columns_include_graph_metrics(self) -> None:
        from src.api.schemas import ExpertResult, SearchResponse

        response = SearchResponse(
            query="test",
            search_mode="profile",
            count=1,
            weights=FusionWeightsApplied(keywords=0.25, semantic=0.55, community=0.2),
            graph_metrics=True,
            results=[
                ExpertResult(
                    rank=1,
                    profile_id="alice",
                    name="Anna",
                    email="",
                    profile_url="https://example.test/p",
                    final=0.9,
                    bm25=0.8,
                    cosine=0.7,
                    ppr=0.6,
                    coauth_degree=4,
                    network_pagerank=0.042,
                    cluster_name="Hub",
                ),
            ],
        )
        columns = csv_columns_for_response(response)
        self.assertIn("coauth_degree", columns)
        self.assertIn("network_pagerank", columns)
        self.assertIn("cluster_name", columns)

    def test_search_requires_query(self) -> None:
        response = self.client.get("/api/search", params={"q": "  "})
        self.assertEqual(response.status_code, 400)

    def test_search_rejects_partial_pubs_since_filter(self) -> None:
        response = self.client.get(
            "/api/search",
            params={"q": "biology", "min_pubs_since": 2},
        )
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

    @patch("src.api.search_service.resolve_institution_filter_ids")
    def test_search_rejects_unknown_institution_name(self, mock_resolve: unittest.mock.MagicMock) -> None:
        mock_resolve.return_value = ([], {"Unknown Uni": []})
        response = self.client.get(
            "/api/search",
            params={"q": "biology", "institution_name": "Unknown Uni"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("No institutions matched", response.json()["detail"])

    @patch("src.api.search_service.query_experts")
    def test_search_disable_ppr(self, mock_query: unittest.mock.MagicMock) -> None:
        mock_query.return_value = []
        response = self.client.get(
            "/api/search",
            params={"q": "biology", "disable_ppr": "true", "w_ppr": 0.5},
        )
        self.assertEqual(response.status_code, 200)
        mock_query.assert_called_once()
        self.assertTrue(mock_query.call_args.kwargs["disable_ppr"])

    @patch("src.api.search_service.get_graph_metrics_store")
    @patch("src.api.search_service.query_experts")
    def test_search_graph_metrics_enriched(
        self,
        mock_query: unittest.mock.MagicMock,
        mock_store: unittest.mock.MagicMock,
    ) -> None:
        mock_store.return_value = GraphMetricsStore(
            researchers={
                "alice": ResearcherGraphMetrics(
                    coauth_degree=5,
                    network_pagerank=0.042,
                    cluster_name="Hub Person",
                ),
            },
            institutions={},
        )
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
        ]
        response = self.client.get(
            "/api/search",
            params={"q": "biology", "mode": "profile", "top": 10},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["graph_metrics"])
        self.assertFalse(payload["static_network_fusion"])
        self.assertTrue(payload["show_community_column"])
        self.assertEqual(payload["results"][0]["coauth_degree"], 5)
        self.assertAlmostEqual(payload["results"][0]["network_pagerank"], 0.042)
        self.assertEqual(payload["results"][0]["cluster_name"], "Hub Person")

    @patch("src.api.search_service.get_graph_metrics_store")
    @patch("src.api.search_service.query_experts")
    def test_static_network_fusion_flag(
        self,
        mock_query: unittest.mock.MagicMock,
        mock_store: unittest.mock.MagicMock,
    ) -> None:
        store = GraphMetricsStore(
            researchers={
                "alice": ResearcherGraphMetrics(
                    coauth_degree=1,
                    network_pagerank=0.05,
                ),
            },
            institutions={},
        )
        mock_store.return_value = store
        mock_query.return_value = [
            QueryResult(
                profile_id="alice",
                rank=1,
                final=0.9,
                bm25=0.8,
                cosine=0.7,
                ppr=0.05,
                search_mode="profile",
            ),
        ]
        response = self.client.get(
            "/api/search",
            params={
                "q": "biology",
                "disable_ppr": "true",
                "w_ppr": 0.2,
                "w_bm25": 0.4,
                "w_embed": 0.4,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["static_network_fusion"])
        self.assertFalse(payload["show_community_column"])
        self.assertGreater(payload["weights"]["community"], 0.0)
        self.assertIs(mock_query.call_args.kwargs["graph_metrics_store"], store)

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
        self.assertIn("community", lines[0])
        self.assertIn("bob", lines[1])

    @patch("src.api.search_service.query_experts")
    def test_search_export_csv_omits_community_when_ppr_disabled(
        self, mock_query: unittest.mock.MagicMock
    ) -> None:
        mock_query.return_value = [
            QueryResult(
                profile_id="bob",
                rank=1,
                final=1.0,
                bm25=1.0,
                cosine=1.0,
                ppr=0.42,
                search_mode="publications",
            ),
        ]
        response = self.client.get(
            "/api/search/export.csv",
            params={"q": "test", "mode": "publications", "disable_ppr": "true"},
        )
        self.assertEqual(response.status_code, 200)
        header = response.content.decode("utf-8-sig").splitlines()[0]
        self.assertNotIn("community", header)

    def test_index_html(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Expert search", response.text)


if __name__ == "__main__":
    unittest.main()
