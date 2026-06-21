from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ludzie_nauki import db
from ludzie_nauki.http_client import HttpClient, RadonClient
from ludzie_nauki.pass1 import run_pass1, run_pass1_single_profile
from ludzie_nauki.pass2 import run_pass2
from ludzie_nauki.pass3 import run_pass3
from ludzie_nauki.pass4 import run_pass4
from ludzie_nauki.radon_queue import drain_radon_queue


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")


def _normalize_code_list(raw: list[str] | None) -> list[str] | None:
    if not raw:
        return None
    out = [str(x).strip() for x in raw if x and str(x).strip()]
    return out or None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ludzie Nauki → SQLite ETL (public API)")
    p.add_argument("--db", required=True, help="SQLite database path")
    p.add_argument("--pass1-only", action="store_true", help="Run Pass 1 only (search + profile enrichment)")
    p.add_argument("--pass2-only", action="store_true", help="Run Pass 2 only (publications + authorship)")
    p.add_argument(
        "--pass3-only",
        action="store_true",
        help="Run Pass 3 only: enrich each is_stub=1 profile then ingest its publications; repeat rounds until none left",
    )
    p.add_argument(
        "--pass4-only",
        action="store_true",
        help="Run Pass 4 only: ingest projects and patents for all non-stub profiles",
    )
    p.add_argument("--page-size", type=int, default=1000, help="scientistSearchData page size (default 1000)")
    p.add_argument("--pub-page-size", type=int, default=500, help="publications list page size (default 500)")
    p.add_argument("--project-page-size", type=int, default=500, help="projects list page size (default 500)")
    p.add_argument("--patent-page-size", type=int, default=500, help="patents list page size (default 500)")
    p.add_argument(
        "--domain",
        action="append",
        metavar="CODE",
        dest="domains",
        help="Pass 1 scientistSearchData filter: domains=CODE (repeat for multiple: --domain DZ0102N --domain DZ0106N)",
    )
    p.add_argument(
        "--discipline",
        action="append",
        metavar="CODE",
        dest="disciplines",
        help="scientistSearchData disciplines=CODE (repeat); with --pass1-manual-slices requires --domain (dictionary crawl default omits domains OK)",
    )
    p.add_argument(
        "--degree-title",
        action="append",
        metavar="CODE",
        dest="degree_titles",
        help=(
            "Pass 1 scientistSearchData degreeTitles=CODE (repeat for multiple manual slices). "
            "Default dictionary crawl: limits which degree shards run (whitelist)"
        ),
    )
    p.add_argument(
        "--pass1-manual-slices",
        action="store_true",
        help="Pass 1: one manual scientistSearchData slice from --domain/--discipline/--degree-title (no findDomains×degree dictionary enumeration)",
    )
    p.add_argument(
        "--pass1-shard-crawl",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--dictionary-year",
        type=int,
        default=2020,
        metavar="YEAR",
        help="Year for GET /dictionary/findDomains (shard crawl only)",
    )
    p.add_argument(
        "--max-shards",
        type=int,
        metavar="N",
        help="Shard crawl only: stop after generating N slices (tests / partial crawl)",
    )
    p.add_argument(
        "--per-sort-row-cap",
        type=int,
        default=1000,
        metavar="N",
        help="Max rows consumed per surname sort direction per slice (default 1000)",
    )
    p.add_argument("--max-profiles", type=int, help="Stop Pass 1 after enriching this many matching profiles")
    p.add_argument("--concurrency", type=int, default=4, help="Parallel HTTP workers for Pass 1 (default 4)")
    p.add_argument("--sleep-min", type=float, default=0.5, help="Min jitter sleep after each Ludzie HTTP request")
    p.add_argument("--sleep-max", type=float, default=1.0, help="Max jitter sleep after each Ludzie HTTP request")
    p.add_argument(
        "--radon-sleep-min",
        type=float,
        default=1.5,
        help="Min jitter sleep after each Radon portal-search request (default 1.5)",
    )
    p.add_argument(
        "--radon-sleep-max",
        type=float,
        default=3.0,
        help="Max jitter sleep after each Radon portal-search request (default 3.0)",
    )
    p.add_argument("--max-retries", type=int, default=100, help="Max retries on 429/5xx/network")
    p.add_argument(
        "--single-profile",
        metavar="PROFILE_ID",
        help="Only this profile: skip search crawl; run pass1 enrichment + pass2 pubs (unless pass-only flags)",
    )
    p.add_argument(
        "--radon-live",
        action="store_true",
        help="Pass 1: call Radon during enrichment (default: enqueue institutions only; drain with --radon-drain)",
    )
    p.add_argument(
        "--radon-defer",
        action="store_true",
        help="No-op: deferred Radon is default; use --radon-live if you want inline Radon",
    )
    p.add_argument(
        "--radon-drain",
        action="store_true",
        help="Only drain radon_institution_queue (Radon portal-search + upsert); exit. Run while Pass 1 runs (queue mode is default)",
    )
    p.add_argument(
        "--radon-drain-limit",
        type=int,
        metavar="N",
        help="With --radon-drain: process at most N queue rows then stop",
    )
    p.add_argument(
        "--pass3-max-rounds",
        type=int,
        default=None,
        metavar="N",
        help="With --pass3-only: abort after N rounds if stubs remain (default: unlimited)",
    )
    p.add_argument("--verbose", action="store_true")
    ns = p.parse_args(argv)
    _setup_logging(ns.verbose)

    domains = _normalize_code_list(ns.domains)
    disciplines = _normalize_code_list(ns.disciplines)
    degree_titles = _normalize_code_list(ns.degree_titles)

    if ns.radon_live and ns.radon_defer:
        logging.error("do not combine --radon-live with --radon-defer")
        return 2
    if ns.radon_defer:
        logging.warning("--radon-defer is redundant (deferred Radon is default)")
    radon_defer = not ns.radon_live

    if ns.pass1_shard_crawl and ns.pass1_manual_slices:
        logging.error("do not combine --pass1-shard-crawl with --pass1-manual-slices")
        return 2
    if ns.pass1_shard_crawl:
        logging.warning("--pass1-shard-crawl is obsolete (dictionary shards are default); use --pass1-manual-slices to disable")

    shard_crawl = not ns.pass1_manual_slices

    db_path = Path(ns.db)
    conn = db.connect(db_path)
    db.init_schema(conn)

    if ns.radon_drain:
        radon = RadonClient(
            min_sleep=ns.radon_sleep_min,
            max_sleep=ns.radon_sleep_max,
            max_retries=ns.max_retries,
        )
        try:
            before = db.radon_queue_count(conn)
            done = drain_radon_queue(conn, radon, max_items=ns.radon_drain_limit)
            after = db.radon_queue_count(conn)
            logging.info(
                "Radon queue: processed %s row(s); %s remaining (was %s)",
                done,
                after,
                before,
            )
        finally:
            radon.close()
            conn.close()
        return 0

    if disciplines and not domains and not shard_crawl:
        logging.error("--discipline requires at least one --domain when using --pass1-manual-slices")
        return 2

    client = HttpClient(
        min_sleep=ns.sleep_min,
        max_sleep=ns.sleep_max,
        max_retries=ns.max_retries,
    )
    radon: RadonClient | None = None
    if not radon_defer:
        radon = RadonClient(
            min_sleep=ns.radon_sleep_min,
            max_sleep=ns.radon_sleep_max,
            max_retries=ns.max_retries,
        )
    try:
        only_sum = int(ns.pass1_only) + int(ns.pass2_only) + int(ns.pass3_only) + int(ns.pass4_only)
        if only_sum > 1:
            logging.error("choose at most one of --pass1-only / --pass2-only / --pass3-only / --pass4-only")
            return 2

        single = (ns.single_profile or "").strip()
        if ns.pass3_only and single:
            logging.error("--pass3-only processes all stubs; omit --single-profile")
            return 2

        do_pass3 = ns.pass3_only
        do_pass4 = ns.pass4_only
        do_p1 = (not ns.pass2_only) and not do_pass3 and not do_pass4
        do_p2 = (not ns.pass1_only) and not do_pass3 and not do_pass4
        if radon_defer and (ns.pass2_only or ns.pass4_only):
            logging.warning("Radon deferral ignored with --pass2-only / --pass4-only (no Pass 1 employments)")

        if single and ns.max_profiles is not None:
            logging.warning("--max-profiles ignored when --single-profile is set")
        if single and (
            domains or disciplines or degree_titles or ns.pass1_manual_slices or ns.pass1_shard_crawl
        ):
            logging.warning(
                "--domain / --discipline / --degree-title / --pass1-manual-slices (--pass1-shard-crawl) ignored "
                "for Pass 1 with --single-profile (no search crawl)"
            )

        if do_pass3:
            stats = run_pass3(
                conn,
                client,
                radon_client=radon,
                radon_defer=radon_defer,
                pub_page_size=ns.pub_page_size,
                max_rounds=ns.pass3_max_rounds,
            )
            logging.info(
                "Pass 3 rounds=%s pass1_returns=%s pass2_profiles=%s",
                stats["rounds"],
                stats["profiles_enriched"],
                stats["profiles_pub_pass"],
            )
        if do_p1:
            if single:
                n = run_pass1_single_profile(
                    conn,
                    client,
                    single,
                    radon_client=radon,
                    radon_defer=radon_defer,
                    search_domains=domains,
                    search_disciplines=disciplines,
                )
            else:
                n = run_pass1(
                    conn,
                    client,
                    radon_client=radon,
                    radon_defer=radon_defer,
                    page_size=ns.page_size,
                    search_domains=domains,
                    search_disciplines=disciplines,
                    search_degree_titles=degree_titles,
                    shard_crawl=shard_crawl,
                    dictionary_year=ns.dictionary_year,
                    max_shards=ns.max_shards,
                    per_sort_row_cap=max(1, ns.per_sort_row_cap),
                    max_profiles=ns.max_profiles,
                    concurrency=max(1, ns.concurrency),
                )
            logging.info("Pass 1 enriched %s profiles", n)
        if do_p2:
            n2 = run_pass2(
                conn,
                client,
                domain_codes=None if single else domains,
                discipline_codes=None if single else disciplines,
                pub_page_size=ns.pub_page_size,
                single_profile_id=single or None,
            )
            logging.info("Pass 2 processed %s profiles", n2)
        if do_pass4:
            n4 = run_pass4(
                conn,
                client,
                domain_codes=None if single else domains,
                discipline_codes=None if single else disciplines,
                project_page_size=ns.project_page_size,
                patent_page_size=ns.patent_page_size,
                single_profile_id=single or None,
            )
            logging.info("Pass 4 processed %s profiles", n4)
    finally:
        if radon is not None:
            radon.close()
        client.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
