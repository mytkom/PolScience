"""BM25Okapi lexical index for wide recall (top recall_k scientists per query)."""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

from src.retrieval.corpus import ScientistDocument, iter_tokenized, tokenize
from src.retrieval.logging_config import get_build_logger

BM25_FILENAME = "bm25_index.pkl"


@dataclass(slots=True)
class Bm25Index:
    bm25: BM25Okapi
    tokenized_corpus: list[list[str]]
    profile_ids: list[str]

    def search(self, query: str, *, top_k: int) -> list[tuple[str, float]]:
        if not self.profile_ids or top_k <= 0:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(
            enumerate(scores),
            key=lambda item: item[1],
            reverse=True,
        )[:top_k]
        return [(self.profile_ids[idx], float(score)) for idx, score in ranked]


def build_bm25_index(documents: list[ScientistDocument]) -> Bm25Index:
    logger = get_build_logger()
    profile_ids = [doc.profile_id for doc in documents]
    logger.info("Tokenizing %d documents for BM25...", len(documents))
    tokenized_corpus = list(iter_tokenized(documents))
    avg_tokens = (
        int(sum(len(t) for t in tokenized_corpus) / len(tokenized_corpus))
        if tokenized_corpus
        else 0
    )
    logger.info("BM25: avg %d tokens per document", avg_tokens)
    bm25 = BM25Okapi(tokenized_corpus or [[""]])
    logger.info("BM25Okapi index ready (%d documents)", len(profile_ids))
    return Bm25Index(bm25=bm25, tokenized_corpus=tokenized_corpus, profile_ids=profile_ids)


def save_bm25_index(index: Bm25Index, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(index, handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_bm25_index(path: Path) -> Bm25Index:
    with path.open("rb") as handle:
        loaded = pickle.load(handle)
    if not isinstance(loaded, Bm25Index):
        raise TypeError(f"Expected Bm25Index in {path}, got {type(loaded)}")
    return loaded
