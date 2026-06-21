"""sentence-transformers bi-encoder: offline corpus vectors, query-time cosine on BM25 pool."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from src.retrieval.logging_config import get_build_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDINGS_FILENAME = "embeddings.f32.npy"
EMBEDDINGS_META_FILENAME = "embeddings_meta.json"

_MODEL_CACHE: dict[str, SentenceTransformer] = {}
_MODEL_LOCK = threading.Lock()
_API_LOG = logging.getLogger("polscience.api")


def get_embedding_model(model_name: str) -> SentenceTransformer:
    """Return a cached SentenceTransformer instance (loads once per model_name)."""
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(model_name)
        if cached is not None:
            return cached
    # Load outside lock so other threads are not blocked for the full download/init.
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    with _MODEL_LOCK:
        existing = _MODEL_CACHE.get(model_name)
        if existing is not None:
            return existing
        _MODEL_CACHE[model_name] = model
        return model


def preload_embedding_model(model_name: str) -> None:
    """Load model weights into memory (call once at API startup)."""
    _API_LOG.info("Loading embedding model into memory: %s", model_name)
    get_embedding_model(model_name)
    _API_LOG.info("Embedding model ready: %s", model_name)


def resolve_model_name_from_artifacts(artifacts_dir: Path) -> str:
    """Read model name from embeddings_meta.json (publications, then profile)."""
    for sub in ("publications", "profile", ""):
        meta_path = artifacts_dir / sub / EMBEDDINGS_META_FILENAME if sub else artifacts_dir / EMBEDDINGS_META_FILENAME
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            name = str(meta.get("model_name") or "").strip()
            if name:
                return name
    return DEFAULT_MODEL


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
    logger.info("Encoding %d texts with model %s (batch_size=%d)...", len(texts), model_name, batch_size)
    model = get_embedding_model(model_name)
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
    name = model_name or DEFAULT_MODEL
    model = get_embedding_model(name)
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
