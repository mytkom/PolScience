"""Scientist co-authorship graph (edge weight = shared publication count) for PPR."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
from scipy import sparse

from src.graph.publication_graph import ensure_graph_indexes
from src.retrieval.corpus import profile_id_to_index
from src.retrieval.logging_config import get_build_logger, log_progress, log_step

COAUTH_EDGES_FILENAME = "coauth_edges.npz"
COAUTH_META_FILENAME = "coauth_graph_meta.json"
EDGE_LOG_INTERVAL = 100_000


def export_coauth_edges(
    conn: sqlite3.Connection,
    profile_ids: list[str],
    artifacts_dir: Path,
) -> sparse.csr_matrix:
    logger = get_build_logger()
    ensure_graph_indexes(conn)
    id_to_idx = profile_id_to_index(profile_ids)
    n = len(profile_ids)
    logger.info("Co-auth graph: %d nodes (indexed profiles)", n)

    rows: list[int] = []
    cols: list[int] = []
    weights: list[float] = []

    sql = """
        SELECT a1.profile_id, a2.profile_id, COUNT(DISTINCT a1.publication_id) AS weight
        FROM authorship a1
        JOIN authorship a2
          ON a1.publication_id = a2.publication_id
         AND a1.profile_id < a2.profile_id
        GROUP BY a1.profile_id, a2.profile_id
    """
    edge_count = 0
    skipped = 0
    logger.info("Running co-authorship SQL (this can take several minutes on large DBs)...")
    for row in conn.execute(sql):
        edge_count += 1
        log_progress(
            logger,
            "  co-auth pairs processed: %d",
            current=edge_count,
            interval=EDGE_LOG_INTERVAL,
        )
        p1 = str(row[0])
        p2 = str(row[1])
        i = id_to_idx.get(p1)
        j = id_to_idx.get(p2)
        if i is None or j is None:
            skipped += 1
            continue
        weight = float(row[2] or 1.0)
        rows.extend([i, j])
        cols.extend([j, i])
        weights.extend([weight, weight])

    logger.info(
        "Co-auth SQL finished: %d undirected pairs, %d kept in index, %d skipped (outside index)",
        edge_count,
        edge_count - skipped,
        skipped,
    )

    with log_step(logger, "Build sparse adjacency matrix", nnz=len(weights)):
        matrix = sparse.csr_matrix(
            (np.asarray(weights, dtype=np.float64), (rows, cols)),
            shape=(n, n),
        )

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    out_path = artifacts_dir / COAUTH_EDGES_FILENAME
    with log_step(logger, "Write coauth_edges.npz", path=out_path):
        sparse.save_npz(out_path, matrix)

    meta = {
        "n_nodes": n,
        "n_edges_undirected": edge_count - skipped,
        "n_pairs_from_sql": edge_count,
        "n_skipped": skipped,
        "profile_count": len(profile_ids),
    }
    meta_path = artifacts_dir / COAUTH_META_FILENAME
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info(
        "Co-auth graph saved: %d nodes, %d edges, matrix nnz=%d, file=%.2f MB",
        n,
        meta["n_edges_undirected"],
        matrix.nnz,
        out_path.stat().st_size / (1024 * 1024) if out_path.is_file() else 0,
    )
    return matrix


def load_coauth_graph(artifacts_dir: Path) -> sparse.csr_matrix:
    path = artifacts_dir / COAUTH_EDGES_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"Co-authorship graph not found: {path}")
    return sparse.load_npz(path)
