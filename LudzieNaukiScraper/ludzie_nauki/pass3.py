"""Stub drain: enrich is_stub=1 profiles (Pass1-style) then ingest publications (Pass2-style), repeat by round."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ludzie_nauki import db
from ludzie_nauki.http_client import HttpClient, RadonClient
from ludzie_nauki.pass1 import run_pass1_single_profile
from ludzie_nauki.pass2 import run_pass2

LOG = logging.getLogger(__name__)


def run_pass3(
    conn,
    client: HttpClient,
    *,
    radon_client: Optional[RadonClient] = None,
    radon_defer: bool = True,
    pub_page_size: int = 500,
    max_rounds: Optional[int] = None,
    progress: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, int]:
    """
    Process all stub profiles in rounds. Each round snapshots current is_stub=1 ids; for each id
    run Pass1 single enrichment then Pass2 pubs (which may create new stubs for coauthors).
    Returns counts: rounds, profiles_enriched (pass1 successes), profiles_pub_pass (pass2 loops).
    """
    rounds = 0
    profiles_enriched = 0
    profiles_pub_pass = 0
    while True:
        stub_ids = db.list_stub_profile_ids(conn)
        if not stub_ids:
            break
        rounds += 1
        if max_rounds is not None and rounds > max_rounds:
            LOG.warning(
                "Pass3: stopping after %s rounds (%s stub(s) remain); raise --pass3-max-rounds or fix data",
                max_rounds,
                len(stub_ids),
            )
            break
        LOG.info("Pass3 round %s: %s stub profile(s)", rounds, len(stub_ids))
        for pid in stub_ids:
            n = run_pass1_single_profile(
                conn,
                client,
                pid,
                radon_client=radon_client,
                radon_defer=radon_defer,
            )
            profiles_enriched += n
            run_pass2(conn, client, pub_page_size=pub_page_size, single_profile_id=pid)
            profiles_pub_pass += 1
            if progress:
                progress(pid, {"round": rounds, "pass3_enriched_running": profiles_enriched})
    return {
        "rounds": rounds,
        "profiles_enriched": profiles_enriched,
        "profiles_pub_pass": profiles_pub_pass,
    }
