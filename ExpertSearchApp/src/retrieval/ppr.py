"""Personalized PageRank on co-authorship graph; seeds from top BM25 hits."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from scipy import sparse

DEFAULT_ALPHA = 0.85
DEFAULT_MAX_ITER = 100
DEFAULT_TOL = 1e-6


def _transition_matrix(adjacency: sparse.csr_matrix) -> sparse.csr_matrix:
    # Row-stochastic: walk to neighbor proportional to edge weight; self-loop if degree 0
    adjacency = adjacency.tocsr()
    out_degree = np.asarray(adjacency.sum(axis=1)).flatten()
    n = adjacency.shape[0]
    row_indices: list[int] = []
    col_indices: list[int] = []
    data: list[float] = []

    for row in range(n):
        start = adjacency.indptr[row]
        end = adjacency.indptr[row + 1]
        deg = out_degree[row]
        if deg <= 0:
            row_indices.append(row)
            col_indices.append(row)
            data.append(1.0)
            continue
        for idx in range(start, end):
            col = int(adjacency.indices[idx])
            row_indices.append(row)
            col_indices.append(col)
            data.append(float(adjacency.data[idx]) / deg)

    return sparse.csr_matrix(
        (np.asarray(data, dtype=np.float64), (row_indices, col_indices)),
        shape=(n, n),
    )


def _personalization_vector(
    n: int,
    seeds: Mapping[int, float],
) -> np.ndarray:
    vec = np.zeros(n, dtype=np.float64)
    if not seeds:
        vec.fill(1.0 / n)
        return vec
    for idx, weight in seeds.items():
        if 0 <= idx < n and weight > 0:
            vec[idx] += float(weight)
    total = vec.sum()
    if total <= 0:
        vec.fill(1.0 / n)
    else:
        vec /= total
    return vec


def personalized_pagerank(
    adjacency: sparse.csr_matrix,
    seeds: Mapping[int, float],
    *,
    alpha: float = DEFAULT_ALPHA,
    max_iter: int = DEFAULT_MAX_ITER,
    tol: float = DEFAULT_TOL,
) -> np.ndarray:
    n = adjacency.shape[0]
    if n == 0:
        return np.array([], dtype=np.float64)

    transition = _transition_matrix(adjacency)
    personalize = _personalization_vector(n, seeds)
    rank = personalize.copy()

    for _ in range(max_iter):
        prev = rank
        rank = alpha * personalize + (1.0 - alpha) * (transition.T @ prev)
        if np.linalg.norm(rank - prev, 1) < tol:
            break

    total = rank.sum()
    if total > 0:
        rank /= total
    return rank


def seeds_from_bm25_hits(
    bm25_hits: list[tuple[str, float]],
    profile_id_to_idx: dict[str, int],
    *,
    seed_k: int,
) -> dict[int, float]:
    seeds: dict[int, float] = {}
    for profile_id, score in bm25_hits[:seed_k]:
        idx = profile_id_to_idx.get(profile_id)
        if idx is None:
            continue
        weight = max(0.0, float(score))
        if weight > 0:
            seeds[idx] = weight
    if not seeds and bm25_hits:
        for profile_id, _ in bm25_hits[:seed_k]:
            idx = profile_id_to_idx.get(profile_id)
            if idx is not None:
                seeds[idx] = 1.0
    return seeds


def ppr_scores_for_candidates(
    adjacency: sparse.csr_matrix,
    seeds: Mapping[int, float],
    candidate_indices: list[int],
    *,
    alpha: float = DEFAULT_ALPHA,
) -> dict[int, float]:
    rank = personalized_pagerank(adjacency, seeds, alpha=alpha)
    return {idx: float(rank[idx]) for idx in candidate_indices if 0 <= idx < len(rank)}
