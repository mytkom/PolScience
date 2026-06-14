#!/usr/bin/env python3
"""CLI for expert retrieval: build-index (offline) and query (BM25 + embed + PPR fusion).

Delegates to src.retrieval.pipeline. Logs during build go to stderr (use -v / --quiet).

Examples:
  python scripts/query_experts.py build-index --db data/LudzieNaukiDumpDB/new_prof_search.sqlite
  python scripts/query_experts.py query --query "quantum error correction" --top 1000 --output results.csv
  python scripts/query_experts.py query --search-mode profile --query "nauki biologiczne" --top 1000
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.retrieval.embeddings import DEFAULT_MODEL  # noqa: E402
from src.retrieval.fusion import FusionWeights  # noqa: E402
from src.retrieval.logging_config import configure_build_logging  # noqa: E402
from src.retrieval.modes import SearchMode  # noqa: E402
from src.retrieval.pipeline import DEFAULT_ARTIFACTS_DIR, build_artifacts, query_experts  # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "LudzieNaukiDumpDB" / "new_prof_search.sqlite"


def _resolve_log_level(args: argparse.Namespace) -> int:
    if getattr(args, "verbose", False):
        return logging.DEBUG
    if getattr(args, "quiet", False):
        return logging.WARNING
    return logging.INFO


def _cmd_build_index(args: argparse.Namespace) -> int:
    configure_build_logging(_resolve_log_level(args))
    modes = SearchMode.parse_build_modes(args.search_mode)
    manifest = build_artifacts(
        args.db,
        args.artifacts_dir,
        modes=modes,
        model_name=args.model,
        embedding_batch_size=args.batch_size,
        show_progress=not args.quiet,
    )
    print(f"Built index for {manifest['profile_count']} profiles")
    for mode, count in manifest.get("mode_profile_counts", {}).items():
        print(f"  {mode}: {count} documents")
    print(f"Artifacts: {manifest['artifacts_dir']}")
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    mode = SearchMode.parse(args.search_mode)
    weights = FusionWeights(
        bm25=args.w_bm25,
        embed=args.w_embed,
        ppr=args.w_ppr,
    )
    results = query_experts(
        args.artifacts_dir,
        args.query,
        search_mode=mode,
        top_k=args.top,
        recall_k=args.recall_k,
        seed_k=args.seed_k,
        weights=weights,
        gate_bm25=args.gate_bm25,
        ppr_alpha=args.ppr_alpha,
        disable_ppr=args.no_ppr,
        min_pubs=args.min_pubs,
        domain_code=args.domain_code,
        min_year=args.min_year,
        min_pubs_since=args.min_pubs_since,
        since_year=args.since_year,
        min_polon_projects=args.min_polon_projects,
        projects_since_year=args.projects_since_year,
        institution_ids=args.institution_id,
        institution_names=args.institution_name,
        require_mgr_plus=args.min_degree_mgr,
        db_path=args.db,
        model_name=args.model,
    )
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "rank",
                    "profile_id",
                    "search_mode",
                    "final",
                    "bm25",
                    "cosine",
                    "ppr",
                ],
            )
            writer.writeheader()
            for row in results:
                writer.writerow(
                    {
                        "rank": row.rank,
                        "profile_id": row.profile_id,
                        "search_mode": row.search_mode,
                        "final": f"{row.final:.6f}",
                        "bm25": f"{row.bm25:.6f}",
                        "cosine": f"{row.cosine:.6f}",
                        "ppr": f"{row.ppr:.6f}",
                    }
                )
        print(f"Wrote {len(results)} rows to {out_path} ({mode.value} mode)")
    else:
        print(f"search_mode={mode.value}")
        for row in results[: min(20, len(results))]:
            print(
                f"{row.rank:4d}  {row.profile_id}  final={row.final:.4f}  "
                f"bm25={row.bm25:.4f}  cosine={row.cosine:.4f}  ppr={row.ppr:.4f}"
            )
        if len(results) > 20:
            print(f"... ({len(results) - 20} more)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help=f"Artifact directory (default: {DEFAULT_ARTIFACTS_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser(
        "build-index",
        help="Build corpus, BM25, embeddings (per mode), and shared co-auth graph",
    )
    build_p.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    build_p.add_argument(
        "--search-mode",
        default="all",
        metavar="MODE",
        help="Index to build: publications, profile, or all (default: all)",
    )
    build_p.add_argument("--model", default=DEFAULT_MODEL, help="sentence-transformers model")
    build_p.add_argument("--batch-size", type=int, default=64, help="Embedding batch size")
    build_p.add_argument(
        "--quiet",
        action="store_true",
        help="Less logging (WARNING) and no sentence-transformers progress bar",
    )
    build_p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging (SQL phases, detailed stats)",
    )
    build_p.set_defaults(func=_cmd_build_index)

    query_p = sub.add_parser("query", help="Run fusion query")
    query_p.add_argument("--query", required=True, help="Topic query string")
    query_p.add_argument(
        "--search-mode",
        default=SearchMode.PUBLICATIONS.value,
        metavar="MODE",
        help=(
            "publications: titles + keywords + taxonomy (specific topics); "
            "profile: keywords, specialties, domains, institutions (exploratory)"
        ),
    )
    query_p.add_argument("--top", type=int, default=1000, help="Number of results to return")
    query_p.add_argument("--output", type=Path, help="CSV output path")
    query_p.add_argument("--recall-k", type=int, default=5000, help="BM25 pool size")
    query_p.add_argument("--seed-k", type=int, default=200, help="PPR seed count")
    query_p.add_argument("--w-bm25", type=float, default=0.25, help="Fusion weight for BM25")
    query_p.add_argument("--w-embed", type=float, default=0.55, help="Fusion weight for embeddings")
    query_p.add_argument("--w-ppr", type=float, default=0.20, help="Fusion weight for PPR")
    query_p.add_argument("--no-ppr", action="store_true", help="Skip co-authorship PPR (Keywords + Semantic only)")
    query_p.add_argument("--gate-bm25", action="store_true", help="Multiply final by (eps + norm_bm25)")
    query_p.add_argument("--ppr-alpha", type=float, default=0.85, help="PPR restart probability")
    query_p.add_argument("--min-pubs", type=int, help="Filter: minimum total publication count")
    query_p.add_argument("--domain-code", help="Filter: profiles.domain_code")
    query_p.add_argument("--min-year", type=int, help="Filter: latest publication year >= value")
    query_p.add_argument(
        "--min-pubs-since",
        type=int,
        help="Filter: minimum publication count since --since-year (requires both)",
    )
    query_p.add_argument("--since-year", type=int, help="Filter: publication year threshold (with --min-pubs-since)")
    query_p.add_argument(
        "--min-polon-projects",
        type=int,
        help="Filter: minimum POLON projects since --projects-since-year (requires both)",
    )
    query_p.add_argument(
        "--projects-since-year",
        type=int,
        help="Filter: POLON project start year threshold (with --min-polon-projects)",
    )
    query_p.add_argument(
        "--institution-id",
        action="append",
        default=None,
        help="Filter: current affiliation at institution UUID (repeatable)",
    )
    query_p.add_argument(
        "--institution-name",
        action="append",
        default=None,
        help="Filter: current affiliation at institution name substring (repeatable)",
    )
    query_p.add_argument(
        "--min-degree-mgr",
        action="store_true",
        help="Filter: require Master's level or above (MGR+)",
    )
    query_p.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="SQLite database (required for institution filter)",
    )
    query_p.add_argument("--model", help="Override embedding model at query time")
    query_p.set_defaults(func=_cmd_query)

    args = parser.parse_args(argv)
    if args.command == "build-index" and not args.db.is_file():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 1
    if args.command == "query":
        if not args.artifacts_dir.is_dir():
            print(f"Artifacts not found: {args.artifacts_dir}", file=sys.stderr)
            print("Run build-index first.", file=sys.stderr)
            return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
