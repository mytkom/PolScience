"""Orchestrate index build and fused expert queries.

build_artifacts: per SearchMode corpus + BM25 + embeddings, then shared co-auth graph.
query_experts: BM25 recall → filter → bi-encoder + PPR on pool → fuse_scores → top_k.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.retrieval.bm25_index import (
    BM25_FILENAME,
    Bm25Index,
    build_bm25_index,
    load_bm25_index,
    save_bm25_index,
)
from src.retrieval.coauth_graph import export_coauth_edges, load_coauth_graph
from src.retrieval.corpus import (
    CORPUS_FILENAME,
    PROFILE_INDEX_FILENAME,
    ScientistDocument,
    build_scientist_corpus,
    load_corpus_jsonl,
    load_profile_id_index,
    mode_artifact_dir,
    profile_id_index,
    profile_id_to_index,
    resolve_mode_dir,
    save_corpus_jsonl,
    save_profile_id_index,
)
from src.retrieval.embeddings import (
    DEFAULT_MODEL,
    build_embeddings,
    cosine_scores_for_profile_ids,
    encode_query,
    load_embeddings,
    save_embeddings,
)
from src.retrieval.filters import (
    count_since_year,
    load_profiles_at_institutions,
    passes_structural_filters,
    resolve_institution_filter_ids,
)
from src.retrieval.fusion import FusionWeights, fuse_scores
from src.retrieval.logging_config import get_build_logger, log_step
from src.retrieval.modes import SearchMode
from src.retrieval.ppr import ppr_scores_for_candidates, seeds_from_bm25_hits

MANIFEST_FILENAME = "build_manifest.json"
DEFAULT_ARTIFACTS_DIR = Path("data/retrieval_artifacts")
_API_LOG = logging.getLogger("polscience.api")

_mode_cache: dict[tuple[str, str], "_ModeArtifacts"] = {}
_shared_cache: dict[str, "_SharedArtifacts"] = {}


@dataclass(slots=True)
class _ModeArtifacts:
    meta_map: dict[str, dict]
    bm25: Bm25Index
    vectors: np.ndarray
    emb_meta: dict
    nonempty_profile_ids: frozenset[str]


@dataclass(slots=True)
class _SharedArtifacts:
    profile_ids: list[str]
    id_to_idx: dict[str, int]
    adjacency: object


@dataclass(slots=True)
class QueryResult:
    profile_id: str
    rank: int
    final: float
    bm25: float
    cosine: float
    ppr: float
    search_mode: str
    pubs_since_year: int | None = None
    projects_since_year: int | None = None


def _passes_filters(
    meta: dict,
    profile_id: str,
    *,
    min_pubs: int | None,
    domain_code: str | None,
    min_year: int | None,
    min_pubs_since: int | None,
    since_year: int | None,
    min_polon_projects: int | None,
    projects_since_year: int | None,
    require_mgr_plus: bool,
    institution_eligible: frozenset[str] | None,
) -> bool:
    return passes_structural_filters(
        meta,
        min_pubs=min_pubs,
        domain_code=domain_code,
        min_year=min_year,
        min_pubs_since=min_pubs_since,
        since_year=since_year,
        min_polon_projects=min_polon_projects,
        projects_since_year=projects_since_year,
        require_mgr_plus=require_mgr_plus,
        institution_eligible=institution_eligible,
        profile_id=profile_id,
    )


def _corpus_stats(documents: list[ScientistDocument]) -> dict[str, float | int]:
    if not documents:
        return {"count": 0, "empty": 0, "avg_chars": 0, "max_chars": 0}
    lengths = [len(doc.text) for doc in documents]
    empty = sum(1 for n in lengths if n == 0)
    return {
        "count": len(documents),
        "empty": empty,
        "avg_chars": int(sum(lengths) / len(lengths)),
        "max_chars": max(lengths),
    }


def _build_mode_indexes(
    conn: sqlite3.Connection,
    artifacts_dir: Path,
    mode: SearchMode,
    *,
    model_name: str,
    embedding_batch_size: int,
    show_progress: bool,
    mode_index: int,
    mode_total: int,
) -> int:
    """One search mode: writes corpus.jsonl, bm25_index.pkl, embeddings under <mode>/."""
    logger = get_build_logger()
    mode_dir = mode_artifact_dir(artifacts_dir, mode)
    logger.info(
        "━━━ Mode %d/%d: %s → %s ━━━",
        mode_index,
        mode_total,
        mode.value,
        mode_dir,
    )

    with log_step(logger, f"[{mode.value}] Load corpus from SQLite"):
        documents = build_scientist_corpus(conn, mode=mode)
    stats = _corpus_stats(documents)
    logger.info(
        "[%s] Corpus: %d profiles, %d empty docs, avg text %d chars, max %d chars",
        mode.value,
        stats["count"],
        stats["empty"],
        stats["avg_chars"],
        stats["max_chars"],
    )

    corpus_path = mode_dir / CORPUS_FILENAME
    with log_step(logger, f"[{mode.value}] Write corpus", path=corpus_path):
        save_corpus_jsonl(documents, corpus_path)
    logger.info("[%s] Wrote %s (%.2f MB)", mode.value, corpus_path.name, _mb(corpus_path))

    with log_step(logger, f"[{mode.value}] Build BM25 index"):
        bm25 = build_bm25_index(documents)
    bm25_path = mode_dir / BM25_FILENAME
    with log_step(logger, f"[{mode.value}] Save BM25 index", path=bm25_path):
        save_bm25_index(bm25, bm25_path)
    logger.info("[%s] Wrote %s (%.2f MB)", mode.value, bm25_path.name, _mb(bm25_path))

    texts = [doc.text for doc in documents]
    with log_step(
        logger,
        f"[{mode.value}] Encode embeddings",
        model=model_name,
        batch_size=embedding_batch_size,
        n_texts=len(texts),
    ):
        vectors = build_embeddings(
            texts,
            model_name=model_name,
            batch_size=embedding_batch_size,
            show_progress=show_progress,
        )
    logger.info(
        "[%s] Embedding matrix shape %s (%.2f MB on disk after save)",
        mode.value,
        vectors.shape,
        vectors.nbytes / (1024 * 1024),
    )
    with log_step(logger, f"[{mode.value}] Save embeddings", dir=mode_dir):
        save_embeddings(vectors, mode_dir, model_name=model_name)

    return len(documents)


def _mb(path: Path) -> float:
    if not path.is_file():
        return 0.0
    return path.stat().st_size / (1024 * 1024)


def build_artifacts(
    db_path: Path,
    artifacts_dir: Path,
    *,
    modes: list[SearchMode] | None = None,  # default: publications + profile
    model_name: str = DEFAULT_MODEL,
    embedding_batch_size: int = 64,
    show_progress: bool = True,
) -> dict:
    logger = get_build_logger()
    build_started = time.perf_counter()
    db_path = db_path.resolve()
    artifacts_dir = artifacts_dir.resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    modes = modes or [SearchMode.PUBLICATIONS, SearchMode.PROFILE]

    logger.info("=" * 60)
    logger.info("Index build started")
    logger.info("  database: %s (%.2f MB)", db_path, _mb(db_path))
    logger.info("  artifacts: %s", artifacts_dir)
    logger.info("  modes: %s", ", ".join(m.value for m in modes))
    logger.info("  embedding model: %s", model_name)
    logger.info("  embedding batch_size: %d", embedding_batch_size)
    logger.info("  sentence-transformers progress bar: %s", show_progress)
    logger.info("=" * 60)

    conn = sqlite3.connect(str(db_path))
    profile_ids: list[str] = []
    try:
        counts: dict[str, int] = {}
        mode_total = len(modes)
        for idx, mode in enumerate(modes, start=1):
            counts[mode.value] = _build_mode_indexes(
                conn,
                artifacts_dir,
                mode,
                model_name=model_name,
                embedding_batch_size=embedding_batch_size,
                show_progress=show_progress,
                mode_index=idx,
                mode_total=mode_total,
            )

        reference_mode = (
            SearchMode.PUBLICATIONS
            if SearchMode.PUBLICATIONS in modes
            else modes[0]
        )
        logger.info("━━━ Shared artifacts ━━━")
        with log_step(logger, "Reload reference corpus for profile index", mode=reference_mode.value):
            documents = build_scientist_corpus(conn, mode=reference_mode)
        profile_ids = profile_id_index(documents)
        index_path = artifacts_dir / PROFILE_INDEX_FILENAME
        with log_step(logger, "Write profile_id_index", path=index_path, n=len(profile_ids)):
            save_profile_id_index(profile_ids, index_path)

        with log_step(
            logger,
            "Export co-authorship graph",
            n_profiles=len(profile_ids),
        ):
            export_coauth_edges(conn, profile_ids, artifacts_dir)
        coauth_path = artifacts_dir / "coauth_edges.npz"
        if coauth_path.is_file():
            logger.info("Co-auth graph file: %.2f MB", _mb(coauth_path))
    finally:
        conn.close()

    elapsed = time.perf_counter() - build_started
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path),
        "profile_count": len(profile_ids),
        "modes_built": [m.value for m in modes],
        "mode_profile_counts": counts,
        "model_name": model_name,
        "artifacts_dir": str(artifacts_dir),
        "build_elapsed_seconds": round(elapsed, 1),
    }
    manifest_path = artifacts_dir / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    logger.info("=" * 60)
    logger.info("Index build finished in %.1fs (%.1f min)", elapsed, elapsed / 60)
    logger.info("  profiles indexed: %d", len(profile_ids))
    for mode, count in counts.items():
        logger.info("  mode %-12s %d documents", mode, count)
    logger.info("  manifest: %s", manifest_path)
    logger.info("=" * 60)
    return manifest


def _load_meta_map(documents: list[ScientistDocument]) -> dict[str, dict]:
    return {doc.profile_id: doc.meta for doc in documents}


def _nonempty_profile_ids(documents: list[ScientistDocument]) -> frozenset[str]:
    return frozenset(
        doc.profile_id for doc in documents if (doc.text or "").strip()
    )


def _load_shared_artifacts(artifacts_dir: Path) -> _SharedArtifacts:
    root = str(artifacts_dir.resolve())
    cached = _shared_cache.get(root)
    if cached is not None:
        return cached
    profile_ids = load_profile_id_index(artifacts_dir / PROFILE_INDEX_FILENAME)
    shared = _SharedArtifacts(
        profile_ids=profile_ids,
        id_to_idx=profile_id_to_index(profile_ids),
        adjacency=load_coauth_graph(artifacts_dir),
    )
    _shared_cache[root] = shared
    return shared


def _load_mode_artifacts(artifacts_dir: Path, search_mode: SearchMode) -> _ModeArtifacts:
    root = str(artifacts_dir.resolve())
    cache_key = (root, search_mode.value)
    cached = _mode_cache.get(cache_key)
    if cached is not None:
        return cached

    mode_dir = resolve_mode_dir(artifacts_dir, search_mode)
    corpus_path = mode_dir / CORPUS_FILENAME
    if not corpus_path.is_file():
        raise FileNotFoundError(
            f"No index for search mode {search_mode.value!r} at {corpus_path}. "
            f"Run build-index (modes: all or {search_mode.value})."
        )

    documents = load_corpus_jsonl(corpus_path)
    vectors, emb_meta = load_embeddings(mode_dir)
    mode_art = _ModeArtifacts(
        meta_map=_load_meta_map(documents),
        bm25=load_bm25_index(mode_dir / BM25_FILENAME),
        vectors=vectors,
        emb_meta=emb_meta,
        nonempty_profile_ids=_nonempty_profile_ids(documents),
    )
    _mode_cache[cache_key] = mode_art
    return mode_art


def preload_search_indexes(artifacts_dir: Path) -> None:
    """Load BM25 + embedding matrices for publications and profile modes into memory."""
    artifacts_dir = artifacts_dir.resolve()
    _API_LOG.info("Preloading search indexes (publications + profile)...")
    _load_shared_artifacts(artifacts_dir)
    for mode in (SearchMode.PUBLICATIONS, SearchMode.PROFILE):
        try:
            _load_mode_artifacts(artifacts_dir, mode)
            _API_LOG.info("Search index ready: mode=%s", mode.value)
        except FileNotFoundError as exc:
            _API_LOG.warning("Skipping index preload for mode %s: %s", mode.value, exc)
    _API_LOG.info("Search index preload complete.")


def clear_search_index_cache() -> None:
    """Drop in-memory indexes (tests or artifact rebuild)."""
    _mode_cache.clear()
    _shared_cache.clear()


def query_experts(
    artifacts_dir: Path,
    query: str,
    *,
    search_mode: SearchMode = SearchMode.PUBLICATIONS,  # which text index to search
    top_k: int = 1000,
    recall_k: int = 5000,
    seed_k: int = 200,
    weights: FusionWeights | None = None,
    gate_bm25: bool = False,
    ppr_alpha: float = 0.85,
    disable_ppr: bool = False,
    min_pubs: int | None = None,
    domain_code: str | None = None,
    min_year: int | None = None,
    min_pubs_since: int | None = None,
    since_year: int | None = None,
    min_polon_projects: int | None = None,
    projects_since_year: int | None = None,
    institution_ids: list[str] | None = None,
    institution_names: list[str] | None = None,
    require_mgr_plus: bool = False,
    db_path: Path | None = None,
    model_name: str | None = None,
) -> list[QueryResult]:
    artifacts_dir = artifacts_dir.resolve()
    mode_art = _load_mode_artifacts(artifacts_dir, search_mode)
    shared = _load_shared_artifacts(artifacts_dir)
    meta_map = mode_art.meta_map
    bm25 = mode_art.bm25
    vectors = mode_art.vectors
    emb_meta = mode_art.emb_meta
    profile_ids = shared.profile_ids
    id_to_idx = shared.id_to_idx
    adjacency = shared.adjacency

    institution_eligible: frozenset[str] | None = None
    resolved_institution_ids: list[str] | None = None
    if institution_ids or institution_names:
        if db_path is None:
            raise ValueError("db_path is required when institution filter is set")
        resolved_institution_ids, _ = resolve_institution_filter_ids(
            db_path,
            institution_ids=institution_ids,
            institution_names=institution_names,
        )
        if not resolved_institution_ids:
            return []
        institution_eligible = load_profiles_at_institutions(db_path, resolved_institution_ids)

    # Stage 1: lexical recall — wide pool (includes zero BM25); skip profiles with empty indexed text
    bm25_hits = bm25.search(query, top_k=recall_k)
    bm25_scores = {pid: score for pid, score in bm25_hits}

    candidate_ids: list[str] = []
    for pid, _ in bm25_hits:
        if pid not in mode_art.nonempty_profile_ids:
            continue
        meta = meta_map.get(pid, {})
        if _passes_filters(
            meta,
            pid,
            min_pubs=min_pubs,
            domain_code=domain_code,
            min_year=min_year,
            min_pubs_since=min_pubs_since,
            since_year=since_year,
            min_polon_projects=min_polon_projects,
            projects_since_year=projects_since_year,
            require_mgr_plus=require_mgr_plus,
            institution_eligible=institution_eligible,
        ):
            candidate_ids.append(pid)

    if not candidate_ids:
        return []

    # Stage 2: semantic similarity on BM25 pool only (not full corpus)
    embed_model = model_name or str(emb_meta.get("model_name") or DEFAULT_MODEL)
    query_vector = encode_query(query, model_name=embed_model)
    embed_scores = cosine_scores_for_profile_ids(
        vectors,
        profile_ids,
        id_to_idx,
        query_vector,
        candidate_ids,
    )

    # Stage 3: graph — PPR from top BM25 seeds, scores for pool nodes only
    if disable_ppr:
        ppr_scores = dict.fromkeys(candidate_ids, 0.0)
    else:
        seeds = seeds_from_bm25_hits(bm25_hits, id_to_idx, seed_k=seed_k)
        candidate_indices = [id_to_idx[pid] for pid in candidate_ids if pid in id_to_idx]
        ppr_raw = ppr_scores_for_candidates(
            adjacency,
            seeds,
            candidate_indices,
            alpha=ppr_alpha,
        )
        ppr_scores = {profile_ids[idx]: score for idx, score in ppr_raw.items()}

    # Stage 4: min-max normalize each signal over pool, weighted sum, sort
    fused = fuse_scores(
        candidate_ids,
        bm25_scores,
        embed_scores,
        ppr_scores,
        weights=weights,
        gate_bm25=gate_bm25,
    )

    show_pubs_since = min_pubs_since is not None and since_year is not None
    show_projects_since = min_polon_projects is not None and projects_since_year is not None

    results: list[QueryResult] = []
    for rank, (pid, final, _parts) in enumerate(fused[:top_k], start=1):
        meta = meta_map.get(pid, {})
        pubs_count = (
            count_since_year(meta.get("pubs_by_year"), since_year)
            if show_pubs_since and since_year is not None
            else None
        )
        projects_count = (
            count_since_year(meta.get("polon_projects_by_year"), projects_since_year)
            if show_projects_since and projects_since_year is not None
            else None
        )
        results.append(
            QueryResult(
                profile_id=pid,
                rank=rank,
                final=final,
                bm25=bm25_scores.get(pid, 0.0),
                cosine=embed_scores.get(pid, 0.0),
                ppr=ppr_scores.get(pid, 0.0),
                search_mode=search_mode.value,
                pubs_since_year=pubs_count,
                projects_since_year=projects_count,
            )
        )
    return results
