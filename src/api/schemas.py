"""Pydantic models for search API responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExpertResult(BaseModel):
    rank: int
    profile_id: str
    name: str
    email: str = ""
    profile_url: str
    final: float
    bm25: float
    cosine: float
    ppr: float


class FusionWeightsApplied(BaseModel):
    """Normalized fusion weights used for this search (sum to 1)."""

    keywords: float
    semantic: float
    community: float


class SearchResponse(BaseModel):
    query: str
    search_mode: str
    count: int
    weights: FusionWeightsApplied
    results: list[ExpertResult] = Field(default_factory=list)


class HealthResponse(BaseModel):
    ok: bool
    db: bool
    artifacts: bool
    db_path: str
    artifacts_dir: str
