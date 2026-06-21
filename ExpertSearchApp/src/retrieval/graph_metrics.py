"""GEXF and build-index graph metrics for expert search enrichment.

This module is the single entry point for network metrics shown in search results
and used for static PageRank fusion when PPR is disabled.

Data sources (merged at API startup via ``preload_graph_metrics``):

1. **Build-index** — ``profile_graph_metrics.npz`` written during ``build-index``
   on the search co-auth graph (``coauth_edges.npz``). Provides co-auth degree and
   global PageRank for all indexed profiles.

2. **GEXF exports** — ``researcher_*.gexf`` and ``institution_full.gexf`` from
   ``generate_graphs.py``. Provides modularity cluster labels and institution metrics;
   may also supply degree/PageRank for domain subsets.

Merge rule: build-index wins for degree/PageRank; GEXF overlays cluster names and
centrality fields. See ``docs/graph_metrics_search.md``.
"""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
from scipy import sparse

from src.retrieval.corpus import PROFILE_INDEX_FILENAME, load_profile_id_index
from src.retrieval.logging_config import get_build_logger, log_step

INSTITUTION_FULL_GEXF = "institution_full.gexf"
RESEARCHER_GEXF_GLOB = "researcher_*.gexf"
PROFILE_METRICS_FILENAME = "profile_graph_metrics.npz"
PROFILE_METRICS_META_FILENAME = "profile_graph_metrics_meta.json"
_GEXF_NS = "http://www.gexf.net/1.2draft"

logger = logging.getLogger("polscience.retrieval.graph_metrics")

_metrics_cache: GraphMetricsStore | None = None


@dataclass(frozen=True, slots=True)
class ResearcherGraphMetrics:
    coauth_degree: int
    network_pagerank: float
    cluster_id: int | None = None
    cluster_name: str | None = None
    betweenness: float | None = None
    closeness: float | None = None
    clustering: float | None = None


@dataclass(frozen=True, slots=True)
class InstitutionGraphMetrics:
    coauth_degree: int
    network_pagerank: float
    cluster_id: int | None = None
    cluster_name: str | None = None
    betweenness: float | None = None
    closeness: float | None = None
    clustering: float | None = None


@dataclass(frozen=True, slots=True)
class GraphMetricsStore:
    researchers: dict[str, ResearcherGraphMetrics]
    institutions: dict[str, InstitutionGraphMetrics]

    @property
    def has_researcher_metrics(self) -> bool:
        return bool(self.researchers)

    @property
    def has_institution_metrics(self) -> bool:
        return bool(self.institutions)

    def researcher_pagerank(self, profile_id: str) -> float | None:
        metrics = self.researchers.get(profile_id)
        return metrics.network_pagerank if metrics is not None else None

    def institution_pagerank(self, institution_id: str) -> float | None:
        metrics = self.institutions.get(institution_id)
        return metrics.network_pagerank if metrics is not None else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required_int(value: Any, default: int = 0) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def _required_float(value: Any, default: float = 0.0) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _parse_gexf_node_metrics(
    attrs: dict[str, Any],
    metrics_cls: type[ResearcherGraphMetrics] | type[InstitutionGraphMetrics],
) -> ResearcherGraphMetrics | InstitutionGraphMetrics:
    return metrics_cls(
        coauth_degree=_required_int(attrs.get("degree")),
        network_pagerank=_required_float(attrs.get("pagerank")),
        cluster_id=_optional_int(attrs.get("community")),
        cluster_name=str(attrs["community_name"]).strip()
        if attrs.get("community_name") not in (None, "")
        else None,
        betweenness=_optional_float(attrs.get("betweenness_centrality")),
        closeness=_optional_float(attrs.get("closeness_centrality")),
        clustering=_optional_float(attrs.get("clustering_coefficient")),
    )


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_gexf_node_attributes(path: Path) -> dict[str, dict[str, str]]:
    """Parse node attributes from GEXF without NetworkX strict typing.

    Some exports declare ``clustering_coefficient`` as ``long`` but store floats;
    NetworkX ``read_gexf`` rejects those files, so we read attvalues directly.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    id_to_title: dict[str, str] = {}
    for elem in root.iter():
        if _local_tag(elem.tag) != "attributes" or elem.get("class") != "node":
            continue
        for attr in elem:
            if _local_tag(attr.tag) != "attribute":
                continue
            attr_id = attr.get("id")
            title = attr.get("title")
            if attr_id and title:
                id_to_title[attr_id] = title

    nodes: dict[str, dict[str, str]] = {}
    for elem in root.iter():
        if _local_tag(elem.tag) != "node":
            continue
        node_id = elem.get("id")
        if not node_id:
            continue
        data: dict[str, str] = {}
        for child in elem:
            if _local_tag(child.tag) != "attvalues":
                continue
            for attvalue in child:
                if _local_tag(attvalue.tag) != "attvalue":
                    continue
                title = id_to_title.get(attvalue.get("for") or "")
                if title:
                    data[title] = attvalue.get("value", "")
        nodes[str(node_id)] = data
    return nodes


def _load_nodes_from_gexf(
    path: Path,
    *,
    metrics_cls: type[ResearcherGraphMetrics] | type[InstitutionGraphMetrics],
) -> dict[str, Any]:
    try:
        raw_nodes = _parse_gexf_node_attributes(path)
    except Exception as exc:
        logger.warning("Failed to parse GEXF %s: %s", path, exc)
        return {}
    out: dict[str, Any] = {}
    for node_id, attrs in raw_nodes.items():
        try:
            out[node_id] = _parse_gexf_node_metrics(attrs, metrics_cls)
        except Exception as exc:
            logger.warning("Skipping GEXF node %s in %s: %s", node_id, path.name, exc)
    return out


def load_graph_metrics(graphs_dir: Path) -> GraphMetricsStore:
    graphs_dir = graphs_dir.resolve()
    if not graphs_dir.is_dir():
        logger.info("Graph metrics directory not found: %s", graphs_dir)
        return GraphMetricsStore(researchers={}, institutions={})

    researchers: dict[str, ResearcherGraphMetrics] = {}
    for path in sorted(graphs_dir.glob(RESEARCHER_GEXF_GLOB)):
        loaded = _load_nodes_from_gexf(path, metrics_cls=ResearcherGraphMetrics)
        researchers.update(loaded)
        logger.info("Loaded researcher GEXF metrics: %s (%d nodes)", path.name, len(loaded))

    institutions: dict[str, InstitutionGraphMetrics] = {}
    institution_path = graphs_dir / INSTITUTION_FULL_GEXF
    if institution_path.is_file():
        institutions = _load_nodes_from_gexf(
            institution_path,
            metrics_cls=InstitutionGraphMetrics,
        )
        logger.info(
            "Loaded institution GEXF metrics: %s (%d nodes)",
            institution_path.name,
            len(institutions),
        )

    return GraphMetricsStore(researchers=researchers, institutions=institutions)


def compute_coauth_degrees(adjacency: sparse.csr_matrix) -> np.ndarray:
    """Unweighted co-author count per indexed profile (matches GEXF ``degree``)."""
    matrix = adjacency.tocsr()
    return np.diff(matrix.indptr).astype(np.int32)


def compute_global_pagerank(adjacency: sparse.csr_matrix) -> np.ndarray:
    """Global PageRank on the weighted co-auth graph, aligned to matrix row order."""
    matrix = adjacency.tocsr()
    n = matrix.shape[0]
    if n == 0:
        return np.array([], dtype=np.float32)
    graph = nx.from_scipy_sparse_array(matrix, parallel_edges=False, create_using=nx.Graph)
    scores = nx.pagerank(graph, weight="weight")
    pagerank = np.zeros(n, dtype=np.float32)
    for node, value in scores.items():
        pagerank[int(node)] = float(value)
    return pagerank


def export_profile_graph_metrics(
    adjacency: sparse.csr_matrix,
    profile_ids: list[str],
    artifacts_dir: Path,
) -> Path:
    """Write degree + PageRank arrays aligned with ``profile_id_index.json``."""
    build_logger = get_build_logger()
    n = len(profile_ids)
    if adjacency.shape[0] != n:
        raise ValueError(
            f"Adjacency shape {adjacency.shape[0]} does not match profile count {n}"
        )

    t0 = time.perf_counter()
    with log_step(build_logger, "Compute co-auth degrees", n_profiles=n):
        degree = compute_coauth_degrees(adjacency)
    with log_step(build_logger, "Compute global PageRank on co-auth graph", n_profiles=n):
        pagerank = compute_global_pagerank(adjacency)

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    out_path = artifacts_dir / PROFILE_METRICS_FILENAME
    with log_step(build_logger, "Write profile graph metrics", path=out_path):
        np.savez_compressed(out_path, degree=degree, pagerank=pagerank)

    meta = {
        "profile_count": n,
        "aligned_with": PROFILE_INDEX_FILENAME,
        "degree_min": int(degree.min()) if n else 0,
        "degree_max": int(degree.max()) if n else 0,
        "degree_zero_count": int((degree == 0).sum()) if n else 0,
        "build_elapsed_seconds": round(time.perf_counter() - t0, 1),
    }
    meta_path = artifacts_dir / PROFILE_METRICS_META_FILENAME
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    build_logger.info(
        "Profile graph metrics saved: %d profiles, %.2f MB, %.1fs",
        n,
        out_path.stat().st_size / (1024 * 1024) if out_path.is_file() else 0,
        meta["build_elapsed_seconds"],
    )
    return out_path


def load_profile_graph_metrics(artifacts_dir: Path) -> dict[str, ResearcherGraphMetrics]:
    """Load build-index metrics; returns empty dict if artifact missing."""
    path = artifacts_dir / PROFILE_METRICS_FILENAME
    index_path = artifacts_dir / PROFILE_INDEX_FILENAME
    if not path.is_file() or not index_path.is_file():
        return {}

    profile_ids = load_profile_id_index(index_path)
    with np.load(path) as data:
        degree = data["degree"]
        pagerank = data["pagerank"]
    if len(profile_ids) != len(degree) or len(profile_ids) != len(pagerank):
        logger.warning(
            "Profile graph metrics length mismatch: index=%d degree=%d pagerank=%d",
            len(profile_ids),
            len(degree),
            len(pagerank),
        )
        return {}

    return {
        profile_id: ResearcherGraphMetrics(
            coauth_degree=int(degree[i]),
            network_pagerank=float(pagerank[i]),
        )
        for i, profile_id in enumerate(profile_ids)
    }


def merge_researcher_metrics(
    index_metrics: dict[str, ResearcherGraphMetrics],
    gexf_metrics: dict[str, ResearcherGraphMetrics],
) -> dict[str, ResearcherGraphMetrics]:
    """Prefer index degree/PageRank; overlay cluster labels from GEXF when present."""
    if not index_metrics:
        return dict(gexf_metrics)
    if not gexf_metrics:
        return dict(index_metrics)

    merged = dict(index_metrics)
    for profile_id, gexf in gexf_metrics.items():
        base = merged.get(profile_id)
        if base is None:
            merged[profile_id] = gexf
            continue
        merged[profile_id] = ResearcherGraphMetrics(
            coauth_degree=base.coauth_degree,
            network_pagerank=base.network_pagerank,
            cluster_id=gexf.cluster_id,
            cluster_name=gexf.cluster_name,
            betweenness=gexf.betweenness,
            closeness=gexf.closeness,
            clustering=gexf.clustering,
        )
    return merged


def get_graph_metrics_store() -> GraphMetricsStore | None:
    return _metrics_cache


def preload_graph_metrics(
    graphs_dir: Path,
    artifacts_dir: Path | None = None,
) -> GraphMetricsStore:
    global _metrics_cache
    gexf_store = load_graph_metrics(graphs_dir)
    index_metrics: dict[str, ResearcherGraphMetrics] = {}
    if artifacts_dir is not None:
        index_metrics = load_profile_graph_metrics(artifacts_dir)
        if index_metrics:
            logger.info(
                "Loaded build-index profile metrics: %d profiles",
                len(index_metrics),
            )
    researchers = merge_researcher_metrics(index_metrics, gexf_store.researchers)
    store = GraphMetricsStore(researchers=researchers, institutions=gexf_store.institutions)
    _metrics_cache = store
    logger.info(
        "Graph metrics preload complete: %d researchers, %d institutions",
        len(store.researchers),
        len(store.institutions),
    )
    return store


def clear_graph_metrics_cache() -> None:
    global _metrics_cache
    _metrics_cache = None


def max_institution_pagerank_for_profile(
    store: GraphMetricsStore,
    profile_institution_ids: list[str],
    filter_institution_ids: frozenset[str],
) -> float | None:
    """Max network PageRank among filter institutions the profile currently holds."""
    matched = [iid for iid in profile_institution_ids if iid in filter_institution_ids]
    if not matched:
        return None
    scores = [
        score
        for iid in matched
        if (score := store.institution_pagerank(iid)) is not None
    ]
    return max(scores) if scores else None
