"""
Generate and export all three graph types from the Polish academic database.

Usage (from project root):
    uv run python src/generate_graphs.py
    uv run python src/generate_graphs.py --domain DZ0102N   # engineering
    uv run python src/generate_graphs.py --top 300          # cap nodes per graph
    uv run python src/generate_graphs.py --no-cache         # force fresh DB queries
    uv run python src/generate_graphs.py --cache-dir data/cache
    uv run python src/generate_graphs.py --domain all --researcher-only --fast
"""
from __future__ import annotations

import argparse
import pickle  # safe: we only load our own Graph objects generated from local DB
import sqlite3
import time
from pathlib import Path

import networkx as nx

from data_loader import (
    Graph,
    load_institution_graph,
    load_researcher_graph,
    load_specialty_graph,
)
from graph_io import assign_communities, assign_metrics, plot_matplotlib, to_gephi, to_networkx


# ── caching ───────────────────────────────────────────────────────────────────

def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.pkl"


def _load_cached(cache_dir: Path, key: str) -> Graph | nx.Graph | None:
    p = _cache_path(cache_dir, key)
    if p.exists():
        print(f"  cache hit  {p.name}")
        with p.open("rb") as f:
            return pickle.load(f)
    return None


def _save_cached(cache_dir: Path, key: str, graph: Graph | nx.Graph) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with _cache_path(cache_dir, key).open("wb") as f:
        pickle.dump(graph, f)
    print(f"  cached     {_cache_path(cache_dir, key).name}")


def _load_graph(
    cache_dir: Path,
    use_cache: bool,
    key: str,
    loader,
    **loader_kwargs,
) -> Graph:
    if use_cache:
        cached = _load_cached(cache_dir, key)
        if cached is not None:
            return cached

    t0 = time.perf_counter()
    graph = loader(**loader_kwargs)
    print(f"  loaded     {len(graph.nodes)} nodes, {len(graph.edges)} edges in {time.perf_counter() - t0:.1f}s")
    _save_cached(cache_dir, key, graph)
    return graph


def _prepare_export_graph(
    cache_dir: Path,
    use_cache: bool,
    key: str,
    raw: Graph,
    *,
    fast: bool,
    directed: bool = False,
) -> nx.Graph:
    """Convert to NetworkX and attach communities + metrics, with optional cache."""
    nx_key = f"{key}_nx_{'fast' if fast else 'full'}"
    if use_cache:
        cached = _load_cached(cache_dir, nx_key)
        if cached is not None:
            return cached

    t0 = time.perf_counter()
    G = to_networkx(raw, directed=directed)
    G = assign_communities(G, fast=fast)
    G = assign_metrics(G, fast=fast)
    elapsed = time.perf_counter() - t0
    mode = "fast" if fast else "full"
    print(
        f"  metrics    {mode} mode on {len(G)} nodes, "
        f"{G.number_of_edges()} edges in {elapsed:.1f}s"
    )
    _save_cached(cache_dir, nx_key, G)
    return G


# ── rendering ─────────────────────────────────────────────────────────────────

def _trim(G: nx.Graph, top_n: int, by: str = "weight") -> nx.Graph:
    """Keep the top_n nodes by weight or degree, and the edges induced by them."""
    if len(G) <= top_n:
        return G
    if by == "degree":
        ranked = sorted(G.nodes(), key=lambda n: G.degree(n), reverse=True)
    else:
        ranked = sorted(G.nodes(), key=lambda n: G.nodes[n].get("weight", 0.0), reverse=True)
    return G.subgraph(set(ranked[:top_n])).copy()


def _save(G: nx.Graph, name: str, out: Path, title: str, **plot_kwargs) -> None:
    import matplotlib.pyplot as plt
    svg_path = out / f"{name}.svg"
    gexf_path = out / f"{name}.gexf"
    print(f"  plotting   {name} ({len(G)} nodes, {G.number_of_edges()} edges) ...", end=" ", flush=True)
    t0 = time.perf_counter()
    fig = plot_matplotlib(G, title=title, **plot_kwargs)
    fig.savefig(svg_path, format="svg", bbox_inches="tight")
    plt.close(fig)
    print(f"saved SVG in {time.perf_counter() - t0:.1f}s")
    to_gephi(G, gexf_path)
    print(f"  exported   {gexf_path.name}")


def _save_gephi_only(G: nx.Graph, name: str, out: Path) -> None:
    gexf_path = out / f"{name}.gexf"
    to_gephi(G, gexf_path)
    print(f"  exported   {gexf_path.name} (Gephi only)")


# ── main ──────────────────────────────────────────────────────────────────────

def generate(
    db_path: Path,
    out_dir: Path,
    cache_dir: Path,
    use_cache: bool,
    domain: str | None,
    top_n: int,
    *,
    researcher_only: bool = False,
    fast: bool = False,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    domain_label = domain or "all_domains"

    conn: sqlite3.Connection | None = None

    def _conn() -> sqlite3.Connection:
        nonlocal conn
        if conn is None:
            conn = sqlite3.connect(db_path)
        return conn

    # ── researcher graph ──────────────────────────────────────────────────────
    print("\n[1/3] Researcher co-authorship graph")
    rg_full = _load_graph(
        cache_dir, use_cache,
        key=f"researcher_{domain_label}_msp2",
        loader=load_researcher_graph,
        conn=_conn(), domain_code=domain, min_shared_pubs=2,
    )
    if rg_full.nodes:
        G_r = _prepare_export_graph(
            cache_dir,
            use_cache,
            key=f"researcher_{domain_label}_msp2",
            raw=rg_full,
            fast=fast,
        )
        _save_gephi_only(G_r, f"researcher_{domain_label}", out_dir)
    else:
        print("  (empty — skipped)")

    if researcher_only:
        if conn is not None:
            conn.close()
        print(f"\nDone. Outputs in {out_dir.resolve()}")
        return

    # ── institution graph ─────────────────────────────────────────────────────
    print("\n[2/3] Institution collaboration graph")
    ig_full = _load_graph(
        cache_dir, use_cache,
        key="institution_msp1",
        loader=load_institution_graph,
        conn=_conn(), min_shared_pubs=1,
    )
    ig = _load_graph(
        cache_dir, use_cache,
        key="institution_msp5",
        loader=load_institution_graph,
        conn=_conn(), min_shared_pubs=5,
    )
    if ig_full.nodes:
        G_i_full = _prepare_export_graph(
            cache_dir,
            use_cache,
            key="institution_msp1",
            raw=ig_full,
            fast=fast,
        )
        _save_gephi_only(G_i_full, "institution_full", out_dir)
    if ig.nodes:
        G_i = _trim(to_networkx(ig), top_n)
        print(f"  trimmed    to {len(G_i)} nodes")
        _save(G_i, "institution", out_dir,
              f"Institution Collaboration — Jaccard % (top {len(G_i)}, min 5 shared pubs)",
              max_edges=150)

    # ── specialty graph ───────────────────────────────────────────────────────
    print("\n[3/3] Specialty co-occurrence graph (directed)")
    sg_full = _load_graph(
        cache_dir, use_cache,
        key="specialty_msp1_pct0",
        loader=load_specialty_graph,
        conn=_conn(), min_shared_researchers=1, min_pct=0.0,
    )
    sg = _load_graph(
        cache_dir, use_cache,
        key="specialty_ms5_pct5",
        loader=load_specialty_graph,
        conn=_conn(), min_shared_researchers=5, min_pct=5.0,
    )
    if sg_full.nodes:
        G_s_full = _prepare_export_graph(
            cache_dir,
            use_cache,
            key="specialty_msp1_pct0",
            raw=sg_full,
            fast=fast,
            directed=True,
        )
        _save_gephi_only(G_s_full, "specialty_full", out_dir)
    if sg.nodes:
        G_s = _trim(to_networkx(sg, directed=True), top_n, by="degree")
        print(f"  trimmed    to {len(G_s)} nodes (top {top_n} by degree)")
        _save(G_s, "specialty", out_dir,
              f"Specialty Co-occurrence — directed (top {len(G_s)}, ≥5 shared, ≥5%)")

    if conn is not None:
        conn.close()
    print(f"\nDone. Outputs in {out_dir.resolve()}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate academic network graphs")
    p.add_argument("--db", type=Path,
                   default=Path(__file__).parent.parent / "data" / "new_prof_search.sqlite")
    p.add_argument("--out", type=Path,
                   default=Path(__file__).parent.parent / "data" / "graphs")
    p.add_argument("--cache-dir", type=Path,
                   default=Path(__file__).parent.parent / "data" / "cache")
    p.add_argument("--no-cache", action="store_true",
                   help="ignore cached graphs and re-query the database")
    p.add_argument("--domain", default="DZ0101N",
                   help="domain_code filter for researcher graph (default: DZ0101N humanities); "
                        "pass '' or 'all' for no filter")
    p.add_argument("--top", type=int, default=60,
                   help="max nodes per graph — keeps top N by degree (default: 60)")
    p.add_argument(
        "--researcher-only",
        action="store_true",
        help="export only the researcher GEXF (skip institution/specialty graphs and SVGs)",
    )
    p.add_argument(
        "--fast",
        action="store_true",
        help="search-oriented metrics: degree + pagerank + Louvain communities; "
             "skip betweenness/closeness/clustering (much faster on all-domains graphs)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    domain = None if args.domain in ("", "all") else args.domain
    generate(
        db_path=args.db,
        out_dir=args.out,
        cache_dir=args.cache_dir,
        use_cache=not args.no_cache,
        domain=domain,
        top_n=args.top,
        researcher_only=args.researcher_only,
        fast=args.fast,
    )
