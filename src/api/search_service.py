"""Run fusion search and merge profile display fields."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from src.api.config import ApiSettings, MAX_TOP_K
from src.api.enrichment import load_profile_displays
from src.api.schemas import ExpertResult, FusionWeightsApplied, SearchResponse
from src.retrieval.fusion import FusionWeights
from src.retrieval.modes import SearchMode
from src.retrieval.pipeline import query_experts


@dataclass(slots=True)
class SearchParams:
    query: str
    mode: SearchMode
    top_k: int = 1000
    recall_k: int = 5000
    seed_k: int = 200
    w_bm25: float = 0.25
    w_embed: float = 0.55
    w_ppr: float = 0.20
    gate_bm25: bool = False
    ppr_alpha: float = 0.85
    min_pubs: int | None = None
    domain_code: str | None = None
    min_year: int | None = None


def run_search(settings: ApiSettings, params: SearchParams) -> SearchResponse:
    top_k = min(max(1, params.top_k), MAX_TOP_K)
    fusion = FusionWeights(
        bm25=params.w_bm25,
        embed=params.w_embed,
        ppr=params.w_ppr,
    )
    weights = fusion.normalized()
    raw = query_experts(
        settings.artifacts_dir,
        params.query,
        search_mode=params.mode,
        top_k=top_k,
        recall_k=params.recall_k,
        seed_k=params.seed_k,
        weights=fusion,
        gate_bm25=params.gate_bm25,
        ppr_alpha=params.ppr_alpha,
        min_pubs=params.min_pubs,
        domain_code=params.domain_code,
        min_year=params.min_year,
    )
    displays = load_profile_displays(
        settings.db_path,
        [r.profile_id for r in raw],
    )
    results: list[ExpertResult] = []
    for row in raw:
        display = displays[row.profile_id]
        results.append(
            ExpertResult(
                rank=row.rank,
                profile_id=row.profile_id,
                name=display.name,
                email=display.email,
                profile_url=display.profile_url,
                final=row.final,
                bm25=row.bm25,
                cosine=row.cosine,
                ppr=row.ppr,
            )
        )
    return SearchResponse(
        query=params.query,
        search_mode=params.mode.value,
        count=len(results),
        weights=FusionWeightsApplied(
            keywords=weights.bm25,
            semantic=weights.embed,
            community=weights.ppr,
        ),
        results=results,
    )


CSV_COLUMNS = [
    "rank",
    "profile_id",
    "name",
    "email",
    "profile_url",
    "final",
    "keywords",
    "semantic",
    "community",
]


def search_response_to_csv(response: SearchResponse) -> bytes:
    """UTF-8 CSV with BOM so Excel on Windows opens Polish diacritics correctly."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for item in response.results:
        writer.writerow(
            {
                "rank": item.rank,
                "profile_id": item.profile_id,
                "name": item.name,
                "email": item.email,
                "profile_url": item.profile_url,
                "final": f"{item.final:.6f}",
                "keywords": f"{item.bm25:.6f}",
                "semantic": f"{item.cosine:.6f}",
                "community": f"{item.ppr:.6f}",
            }
        )
    return buffer.getvalue().encode("utf-8-sig")
