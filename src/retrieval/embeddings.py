"""sentence-transformers bi-encoder: offline corpus vectors, query-time cosine on BM25 pool."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.retrieval.logging_config import get_build_logger

DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDINGS_FILENAME = "embeddings.f32.npy"
EMBEDDINGS_META_FILENAME = "embeddings_meta.json"


def _load_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def build_embeddings(
    texts: list[str],
    *,
    model_name: str = DEFAULT_MODEL,
    batch_size: int = 64,
    show_progress: bool = True,
) -> np.ndarray:
    logger = get_build_logger()
    empty = sum(1 for t in texts if not (t or "").strip())
    if empty:
        logger.warning("%d / %d corpus texts are empty before encoding", empty, len(texts))
    logger.info("Loading sentence-transformers model: %s", model_name)
    model = _load_model(model_name)
    logger.info(
        "Encoding %d texts (batch_size=%d, progress_bar=%s)...",
        len(texts),
        batch_size,
        show_progress,
    )
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=show_progress,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    result = np.asarray(vectors, dtype=np.float32)
    logger.info("Encoding complete: shape=%s dtype=%s", result.shape, result.dtype)
    return result


def save_embeddings(vectors: np.ndarray, artifacts_dir: Path, *, model_name: str) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    np.save(artifacts_dir / EMBEDDINGS_FILENAME, vectors)
    meta = {"model_name": model_name, "dim": int(vectors.shape[1]) if vectors.size else 0}
    (artifacts_dir / EMBEDDINGS_META_FILENAME).write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )


def load_embeddings(artifacts_dir: Path) -> tuple[np.ndarray, dict]:
    vectors = np.load(artifacts_dir / EMBEDDINGS_FILENAME)
    meta_path = artifacts_dir / EMBEDDINGS_META_FILENAME
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return vectors, meta


def encode_query(query: str, *, model_name: str | None = None) -> np.ndarray:
    meta_model = model_name or DEFAULT_MODEL
    model = _load_model(meta_model)
    vector = model.encode(
        [query],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return np.asarray(vector[0], dtype=np.float32)


def cosine_scores_for_indices(
    vectors: np.ndarray,
    query_vector: np.ndarray,
    indices: list[int],
) -> dict[int, float]:
    if not indices:
        return {}
    matrix = vectors[indices]
    scores = matrix @ query_vector
    return {idx: float(scores[pos]) for pos, idx in enumerate(indices)}


def cosine_scores_for_profile_ids(
    vectors: np.ndarray,
    profile_ids: list[str],
    profile_id_to_idx: dict[str, int],
    query_vector: np.ndarray,
    candidate_ids: list[str],
) -> dict[str, float]:
    indices: list[int] = []
    ids: list[str] = []
    for pid in candidate_ids:
        idx = profile_id_to_idx.get(pid)
        if idx is None:
            continue
        indices.append(idx)
        ids.append(pid)
    raw = cosine_scores_for_indices(vectors, query_vector, indices)
    return {ids[pos]: raw[idx] for pos, idx in enumerate(indices)}
