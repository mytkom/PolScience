from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy import sparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.retrieval.corpus import save_profile_id_index  # noqa: E402
from src.retrieval.gexf_metrics import ResearcherGraphMetrics  # noqa: E402
from src.retrieval.profile_graph_metrics import (  # noqa: E402
    PROFILE_METRICS_FILENAME,
    compute_coauth_degrees,
    compute_global_pagerank,
    export_profile_graph_metrics,
    load_profile_graph_metrics,
    merge_researcher_metrics,
)


class TestProfileGraphMetrics(unittest.TestCase):
    def test_compute_degrees_and_pagerank_on_triangle(self) -> None:
        matrix = sparse.csr_matrix(
            (
                [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
                ([0, 0, 1, 1, 2, 2], [1, 2, 0, 2, 0, 1]),
            ),
            shape=(3, 3),
        )
        degree = compute_coauth_degrees(matrix)
        self.assertEqual(degree.tolist(), [2, 2, 2])
        pagerank = compute_global_pagerank(matrix)
        self.assertEqual(len(pagerank), 3)
        self.assertAlmostEqual(float(pagerank.sum()), 1.0, places=5)

    def test_export_and_load_round_trip(self) -> None:
        matrix = sparse.csr_matrix(
            ([2.0, 2.0], ([0, 1], [1, 0])),
            shape=(2, 2),
        )
        profile_ids = ["alice", "bob"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_profile_id_index(profile_ids, root / "profile_id_index.json")
            export_profile_graph_metrics(matrix, profile_ids, root)
            self.assertTrue((root / PROFILE_METRICS_FILENAME).is_file())
            loaded = load_profile_graph_metrics(root)
            self.assertEqual(set(loaded), {"alice", "bob"})
            self.assertEqual(loaded["alice"].coauth_degree, 1)
            self.assertGreater(loaded["alice"].network_pagerank, 0.0)

    def test_merge_prefers_index_degree_and_gexf_cluster(self) -> None:
        index = {
            "alice": ResearcherGraphMetrics(coauth_degree=5, network_pagerank=0.2),
        }
        gexf = {
            "alice": ResearcherGraphMetrics(
                coauth_degree=3,
                network_pagerank=0.05,
                cluster_id=1,
                cluster_name="Hub",
            ),
            "bob": ResearcherGraphMetrics(
                coauth_degree=1,
                network_pagerank=0.01,
                cluster_name="Bob",
            ),
        }
        merged = merge_researcher_metrics(index, gexf)
        self.assertEqual(merged["alice"].coauth_degree, 5)
        self.assertAlmostEqual(merged["alice"].network_pagerank, 0.2)
        self.assertEqual(merged["alice"].cluster_name, "Hub")
        self.assertEqual(merged["bob"].cluster_name, "Bob")


if __name__ == "__main__":
    unittest.main()
