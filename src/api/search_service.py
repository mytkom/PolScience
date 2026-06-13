"""Run fusion search and merge profile display fields."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from src.api.config import ApiSettings, MAX_TOP_K
from src.api.enrichment import load_profile_displays
from src.api.schemas import ExpertResult, FilterColumnsApplied, FusionWeightsApplied, SearchResponse
from src.retrieval.filters import (
    load_current_institution_names,
    load_degree_labels,
    resolve_institution_filter_ids,
)
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
    min_pubs_since: int | None = None
    since_year: int | None = None
    min_polon_projects: int | None = None
    projects_since_year: int | None = None
    institution_ids: list[str] | None = None
    institution_names: list[str] | None = None
    require_mgr_plus: bool = False


def _validate_institution_name_resolution(settings: ApiSettings, params: SearchParams) -> None:
    if not params.institution_names:
        return
    _, name_to_ids = resolve_institution_filter_ids(
        settings.db_path,
        institution_ids=params.institution_ids,
        institution_names=params.institution_names,
    )
    unmatched = [name for name, ids in name_to_ids.items() if not ids]
    if unmatched:
        quoted = ", ".join(f'"{name}"' for name in unmatched)
        raise ValueError(f"No institutions matched name query: {quoted}")


def _build_filter_columns(params: SearchParams) -> FilterColumnsApplied | None:
    columns = FilterColumnsApplied(
        pubs_since_year=params.since_year if params.min_pubs_since is not None else None,
        projects_since_year=(
            params.projects_since_year if params.min_polon_projects is not None else None
        ),
        institutions=bool(params.institution_ids or params.institution_names),
        degree=params.require_mgr_plus,
    )
    if not any(
        (
            columns.pubs_since_year is not None,
            columns.projects_since_year is not None,
            columns.institutions,
            columns.degree,
        )
    ):
        return None
    return columns


def run_search(settings: ApiSettings, params: SearchParams) -> SearchResponse:
    top_k = min(max(1, params.top_k), MAX_TOP_K)
    fusion = FusionWeights(
        bm25=params.w_bm25,
        embed=params.w_embed,
        ppr=params.w_ppr,
    )
    weights = fusion.normalized()
    _validate_institution_name_resolution(settings, params)
    filter_columns = _build_filter_columns(params)
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
        min_pubs_since=params.min_pubs_since,
        since_year=params.since_year,
        min_polon_projects=params.min_polon_projects,
        projects_since_year=params.projects_since_year,
        institution_ids=params.institution_ids,
        institution_names=params.institution_names,
        require_mgr_plus=params.require_mgr_plus,
        db_path=settings.db_path,
    )
    profile_ids = [r.profile_id for r in raw]
    displays = load_profile_displays(settings.db_path, profile_ids)

    institutions_by_profile: dict[str, str] = {}
    if filter_columns and filter_columns.institutions:
        institutions_by_profile = load_current_institution_names(settings.db_path, profile_ids)

    degrees_by_profile: dict[str, str] = {}
    if filter_columns and filter_columns.degree:
        degrees_by_profile = load_degree_labels(settings.db_path, profile_ids)

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
                pubs_since_year=row.pubs_since_year,
                projects_since_year=row.projects_since_year,
                institutions=institutions_by_profile.get(row.profile_id),
                degree=degrees_by_profile.get(row.profile_id),
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
        filter_columns=filter_columns,
        results=results,
    )


BASE_CSV_COLUMNS = [
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

# Backward-compatible alias for tests and callers.
CSV_COLUMNS = BASE_CSV_COLUMNS


def csv_columns_for_response(response: SearchResponse) -> list[str]:
    columns = list(BASE_CSV_COLUMNS)
    fc = response.filter_columns
    if not fc:
        return columns
    if fc.pubs_since_year is not None:
        columns.append(f"pubs_since_{fc.pubs_since_year}")
    if fc.projects_since_year is not None:
        columns.append(f"projects_since_{fc.projects_since_year}")
    if fc.institutions:
        columns.append("institutions")
    if fc.degree:
        columns.append("degree")
    return columns


def search_response_to_csv(response: SearchResponse) -> bytes:
    """UTF-8 CSV with BOM so Excel on Windows opens Polish diacritics correctly."""
    columns = csv_columns_for_response(response)
    fc = response.filter_columns
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for item in response.results:
        row = {
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
        if fc:
            if fc.pubs_since_year is not None:
                row[f"pubs_since_{fc.pubs_since_year}"] = (
                    "" if item.pubs_since_year is None else item.pubs_since_year
                )
            if fc.projects_since_year is not None:
                row[f"projects_since_{fc.projects_since_year}"] = (
                    "" if item.projects_since_year is None else item.projects_since_year
                )
            if fc.institutions:
                row["institutions"] = item.institutions or ""
            if fc.degree:
                row["degree"] = item.degree or ""
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")
