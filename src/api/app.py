"""FastAPI application: expert search API and web UI."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.config import ApiSettings, load_settings
from src.api.schemas import HealthResponse, SearchResponse
from src.api.search_service import SearchParams, run_search, search_response_to_csv
from src.retrieval.embeddings import preload_embedding_model, resolve_model_name_from_artifacts
from src.retrieval.logging_config import configure_build_logging
from src.retrieval.modes import SearchMode
from src.retrieval.pipeline import preload_search_indexes

LOG = logging.getLogger("polscience.api")
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_TEMPLATES = Jinja2Templates(directory=str(_STATIC_DIR))


def _parse_institution_values(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    tokens: list[str] = []
    for raw in values:
        for part in str(raw).split(","):
            token = part.strip()
            if token:
                tokens.append(token)
    return tokens or None


def _validate_paired_int_params(
    first: int | None,
    second: int | None,
    *,
    first_name: str,
    second_name: str,
) -> None:
    if (first is None) != (second is None):
        raise HTTPException(
            status_code=400,
            detail=f"Both {first_name} and {second_name} are required together.",
        )


def _parse_search_params(
    q: str,
    mode: str,
    top: int,
    recall_k: int,
    seed_k: int,
    w_bm25: float,
    w_embed: float,
    w_ppr: float,
    gate_bm25: bool,
    ppr_alpha: float,
    min_pubs: int | None,
    domain_code: str | None,
    min_year: int | None,
    min_pubs_since: int | None,
    since_year: int | None,
    min_polon_projects: int | None,
    projects_since_year: int | None,
    institution_id: list[str] | None,
    institution_name: list[str] | None,
    min_degree_mgr: bool,
) -> SearchParams:
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required.")
    try:
        search_mode = SearchMode.parse(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _validate_paired_int_params(min_pubs_since, since_year, first_name="min_pubs_since", second_name="since_year")
    _validate_paired_int_params(
        min_polon_projects,
        projects_since_year,
        first_name="min_polon_projects",
        second_name="projects_since_year",
    )
    return SearchParams(
        query=query,
        mode=search_mode,
        top_k=top,
        recall_k=recall_k,
        seed_k=seed_k,
        w_bm25=w_bm25,
        w_embed=w_embed,
        w_ppr=w_ppr,
        gate_bm25=gate_bm25,
        ppr_alpha=ppr_alpha,
        min_pubs=min_pubs,
        domain_code=domain_code,
        min_year=min_year,
        min_pubs_since=min_pubs_since,
        since_year=since_year,
        min_polon_projects=min_polon_projects,
        projects_since_year=projects_since_year,
        institution_ids=_parse_institution_values(institution_id),
        institution_names=_parse_institution_values(institution_name),
        require_mgr_plus=min_degree_mgr,
    )


def _warmup_query_paths(settings: ApiSettings) -> None:
    """Optional: run a tiny query per mode to warm fusion code paths."""
    for mode in (SearchMode.PUBLICATIONS, SearchMode.PROFILE):
        try:
            run_search(
                settings,
                SearchParams(query="science", mode=mode, top_k=1, recall_k=10),
            )
        except FileNotFoundError:
            LOG.warning("Skipping query warmup for mode %s: index missing", mode.value)
    LOG.info("Query path warmup complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_build_logging(logging.INFO)
    settings = load_settings()
    app.state.settings = settings
    db_ok, artifacts_ok = settings.validate_paths()
    if not db_ok:
        LOG.error("Database not found: %s", settings.db_path)
    if not artifacts_ok:
        LOG.error("Artifacts directory not found: %s", settings.artifacts_dir)
    if artifacts_ok:
        model_name = resolve_model_name_from_artifacts(settings.artifacts_dir)
        app.state.embedding_model_name = model_name
        preload_embedding_model(model_name)
        preload_search_indexes(settings.artifacts_dir)
    else:
        app.state.embedding_model_name = None
    if settings.eager_load and db_ok and artifacts_ok:
        LOG.info("POLSCIENCE_EAGER_LOAD: running probe queries for both modes...")
        _warmup_query_paths(settings)
    yield


app = FastAPI(
    title="PolScience Expert Search",
    description="BM25 + bi-encoder + PPR fusion over Ludzie Nauki profiles",
    lifespan=lifespan,
)

if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {"request": request},
    )


@app.get("/api/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings: ApiSettings = request.app.state.settings
    db_ok, artifacts_ok = settings.validate_paths()
    return HealthResponse(
        ok=db_ok and artifacts_ok,
        db=db_ok,
        artifacts=artifacts_ok,
        db_path=str(settings.db_path),
        artifacts_dir=str(settings.artifacts_dir),
    )


def _execute_search(request: Request, params: SearchParams) -> SearchResponse:
    settings: ApiSettings = request.app.state.settings
    db_ok, artifacts_ok = settings.validate_paths()
    if not db_ok:
        raise HTTPException(status_code=503, detail=f"Database not found: {settings.db_path}")
    if not artifacts_ok:
        raise HTTPException(
            status_code=503,
            detail=f"Artifacts not found: {settings.artifacts_dir}. Run build-index first.",
        )
    try:
        return run_search(settings, params)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/search", response_model=SearchResponse)
async def api_search(
    request: Request,
    q: Annotated[str, Query(description="Topic query")],
    mode: Annotated[str, Query(description="publications or profile")] = "publications",
    top: Annotated[int, Query(ge=1, le=5000)] = 1000,
    recall_k: Annotated[int, Query(ge=1, le=50000)] = 5000,
    seed_k: Annotated[int, Query(ge=1, le=5000)] = 200,
    w_bm25: Annotated[float, Query(ge=0)] = 0.25,
    w_embed: Annotated[float, Query(ge=0)] = 0.55,
    w_ppr: Annotated[float, Query(ge=0)] = 0.20,
    gate_bm25: bool = False,
    ppr_alpha: Annotated[float, Query(gt=0, lt=1)] = 0.85,
    min_pubs: int | None = None,
    domain_code: str | None = None,
    min_year: int | None = None,
    min_pubs_since: int | None = None,
    since_year: int | None = None,
    min_polon_projects: int | None = None,
    projects_since_year: int | None = None,
    institution_id: Annotated[list[str] | None, Query()] = None,
    institution_name: Annotated[list[str] | None, Query()] = None,
    min_degree_mgr: bool = False,
) -> SearchResponse:
    params = _parse_search_params(
        q,
        mode,
        top,
        recall_k,
        seed_k,
        w_bm25,
        w_embed,
        w_ppr,
        gate_bm25,
        ppr_alpha,
        min_pubs,
        domain_code,
        min_year,
        min_pubs_since,
        since_year,
        min_polon_projects,
        projects_since_year,
        institution_id,
        institution_name,
        min_degree_mgr,
    )
    return _execute_search(request, params)


@app.get("/api/search/export.csv")
async def api_search_export_csv(
    request: Request,
    q: Annotated[str, Query()],
    mode: str = "publications",
    top: Annotated[int, Query(ge=1, le=5000)] = 1000,
    recall_k: Annotated[int, Query(ge=1, le=50000)] = 5000,
    seed_k: Annotated[int, Query(ge=1, le=5000)] = 200,
    w_bm25: Annotated[float, Query(ge=0)] = 0.25,
    w_embed: Annotated[float, Query(ge=0)] = 0.55,
    w_ppr: Annotated[float, Query(ge=0)] = 0.20,
    gate_bm25: bool = False,
    ppr_alpha: Annotated[float, Query(gt=0, lt=1)] = 0.85,
    min_pubs: int | None = None,
    domain_code: str | None = None,
    min_year: int | None = None,
    min_pubs_since: int | None = None,
    since_year: int | None = None,
    min_polon_projects: int | None = None,
    projects_since_year: int | None = None,
    institution_id: Annotated[list[str] | None, Query()] = None,
    institution_name: Annotated[list[str] | None, Query()] = None,
    min_degree_mgr: bool = False,
) -> PlainTextResponse:
    params = _parse_search_params(
        q,
        mode,
        top,
        recall_k,
        seed_k,
        w_bm25,
        w_embed,
        w_ppr,
        gate_bm25,
        ppr_alpha,
        min_pubs,
        domain_code,
        min_year,
        min_pubs_since,
        since_year,
        min_polon_projects,
        projects_since_year,
        institution_id,
        institution_name,
        min_degree_mgr,
    )
    response = _execute_search(request, params)
    csv_body = search_response_to_csv(response)
    safe_mode = SearchMode.parse(mode).value
    filename = f"experts_{safe_mode}.csv"
    return PlainTextResponse(
        content=csv_body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}'
            ),
        },
    )
