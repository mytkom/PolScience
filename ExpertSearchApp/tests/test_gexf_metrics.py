from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.retrieval.graph_metrics import (  # noqa: E402
    GraphMetricsStore,
    InstitutionGraphMetrics,
    ResearcherGraphMetrics,
    clear_graph_metrics_cache,
    load_graph_metrics,
    max_institution_pagerank_for_profile,
    preload_graph_metrics,
)
from src.retrieval.fusion import FusionWeights, fuse_scores  # noqa: E402


def _write_researcher_gexf(path: Path) -> None:
    graph = nx.Graph()
    graph.add_node(
        "alice",
        label="Alice",
        degree=3,
        pagerank=0.042,
        community=1,
        community_name="Hub Person",
        betweenness_centrality=0.01,
        closeness_centrality=0.5,
        clustering_coefficient=0.2,
    )
    graph.add_node("bob", label="Bob", degree=1, pagerank=0.01, community=2, community_name="Bob")
    nx.write_gexf(graph, path)


def _write_institution_gexf(path: Path) -> None:
    graph = nx.Graph()
    graph.add_node(
        "inst-uw",
        label="UW",
        degree=10,
        pagerank=0.15,
        community=0,
        community_name="UW",
    )
    nx.write_gexf(graph, path)


class TestGexfMetrics(unittest.TestCase):
    def tearDown(self) -> None:
        clear_graph_metrics_cache()

    def test_missing_directory_returns_empty_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = load_graph_metrics(Path(tmp) / "missing")
            self.assertEqual(store.researchers, {})
            self.assertFalse(store.has_researcher_metrics)

    def test_load_researcher_and_institution_gexf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_researcher_gexf(root / "researcher_test.gexf")
            _write_institution_gexf(root / "institution_full.gexf")
            store = load_graph_metrics(root)
            self.assertIn("alice", store.researchers)
            alice = store.researchers["alice"]
            self.assertEqual(alice.coauth_degree, 3)
            self.assertAlmostEqual(alice.network_pagerank, 0.042)
            self.assertEqual(alice.cluster_name, "Hub Person")
            self.assertAlmostEqual(alice.betweenness, 0.01)
            self.assertIn("inst-uw", store.institutions)
            self.assertAlmostEqual(store.institutions["inst-uw"].network_pagerank, 0.15)

    def test_preload_graph_metrics_caches_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_researcher_gexf(root / "researcher_test.gexf")
            store = preload_graph_metrics(root)
            from src.retrieval.graph_metrics import get_graph_metrics_store

            self.assertIs(get_graph_metrics_store(), store)

    def test_max_institution_pagerank_for_profile(self) -> None:
        store = GraphMetricsStore(
            researchers={},
            institutions={
                "inst-a": InstitutionGraphMetrics(coauth_degree=1, network_pagerank=0.1),
                "inst-b": InstitutionGraphMetrics(coauth_degree=2, network_pagerank=0.25),
            },
        )
        score = max_institution_pagerank_for_profile(
            store,
            ["inst-a", "inst-b", "inst-c"],
            frozenset({"inst-a", "inst-c"}),
        )
        self.assertAlmostEqual(score, 0.1)


class TestStaticPagerankFusion(unittest.TestCase):
    def test_fusion_uses_static_pagerank_scores(self) -> None:
        fused = fuse_scores(
            ["alice", "bob"],
            bm25_scores={"alice": 1.0, "bob": 1.0},
            embed_scores={"alice": 0.5, "bob": 0.5},
            ppr_scores={"alice": 0.9, "bob": 0.1},
            weights=FusionWeights(bm25=0.0, embed=0.0, ppr=1.0),
        )
        self.assertEqual(fused[0][0], "alice")
        self.assertGreater(fused[0][1], fused[1][1])


if __name__ == "__main__":
    unittest.main()
