"""Precomputed degree and PageRank on the search co-auth graph (build-index)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import networkx as nx
import numpy as np
from scipy import sparse

from src.retrieval.corpus import PROFILE_INDEX_FILENAME, load_profile_id_index
from src.retrieval.gexf_metrics import ResearcherGraphMetrics
from src.retrieval.logging_config import get_build_logger, log_step

logger = logging.getLogger("polscience.retrieval.profile_graph_metrics")

PROFILE_METRICS_FILENAME = "profile_graph_metrics.npz"
PROFILE_METRICS_META_FILENAME = "profile_graph_metrics_meta.json"


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
