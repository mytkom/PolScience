"""Combine normalized BM25, cosine, and PPR scores over the candidate pool."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class FusionWeights:
    bm25: float = 0.25
    embed: float = 0.55
    ppr: float = 0.20

    def normalized(self) -> FusionWeights:
        total = self.bm25 + self.embed + self.ppr
        if total <= 0:
            return FusionWeights(bm25=1 / 3, embed=1 / 3, ppr=1 / 3)
        return FusionWeights(
            bm25=self.bm25 / total,
            embed=self.embed / total,
            ppr=self.ppr / total,
        )


def minmax_normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = np.asarray(list(scores.values()), dtype=np.float64)
    low = float(values.min())
    high = float(values.max())
    if high <= low:
        return {key: 0.0 for key in scores}
    span = high - low
    return {key: (float(value) - low) / span for key, value in scores.items()}


def fuse_scores(
    candidate_ids: list[str],
    bm25_scores: dict[str, float],
    embed_scores: dict[str, float],
    ppr_scores: dict[str, float],
    *,
    weights: FusionWeights | None = None,
    gate_bm25: bool = False,
    gate_epsilon: float = 0.05,
) -> list[tuple[str, float, dict[str, float]]]:
    weights = (weights or FusionWeights()).normalized()
    norm_bm25 = minmax_normalize({pid: bm25_scores.get(pid, 0.0) for pid in candidate_ids})
    norm_embed = minmax_normalize({pid: embed_scores.get(pid, 0.0) for pid in candidate_ids})
    norm_ppr = minmax_normalize({pid: ppr_scores.get(pid, 0.0) for pid in candidate_ids})

    results: list[tuple[str, float, dict[str, float]]] = []
    for pid in candidate_ids:
        parts = {
            "bm25": norm_bm25.get(pid, 0.0),
            "cosine": norm_embed.get(pid, 0.0),
            "ppr": norm_ppr.get(pid, 0.0),
        }
        final = (
            weights.bm25 * parts["bm25"]
            + weights.embed * parts["cosine"]
            + weights.ppr * parts["ppr"]
        )
        if gate_bm25:
            final *= gate_epsilon + parts["bm25"]
        results.append((pid, final, parts))

    results.sort(key=lambda item: item[1], reverse=True)
    return results
