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
    pubs_since_year: int | None = None
    projects_since_year: int | None = None
    institutions: str | None = None
    degree: str | None = None
    coauth_degree: int | None = None
    network_pagerank: float | None = None
    cluster_name: str | None = None
    institution_network_pagerank: float | None = None


class FilterColumnsApplied(BaseModel):
    """Optional result columns enabled by active structural filters."""

    pubs_since_year: int | None = None
    projects_since_year: int | None = None
    institutions: bool = False
    degree: bool = False


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
    filter_columns: FilterColumnsApplied | None = None
    graph_metrics: bool = False
    static_network_fusion: bool = False
    show_community_column: bool = True
    results: list[ExpertResult] = Field(default_factory=list)


class HealthResponse(BaseModel):
    ok: bool
    db: bool
    artifacts: bool
    graphs: bool
    db_path: str
    artifacts_dir: str
    graphs_dir: str
