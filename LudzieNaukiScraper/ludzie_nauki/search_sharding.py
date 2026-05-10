"""Dictionary-driven Pass1 search shards (domain + discipline + degree)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from ludzie_nauki.http_client import HttpClient

_FIND_DOMAINS = "/v1.0/public/dictionary/findDomains"
_DEGREE_TITLES = "/v1.0/public/profile/degreeTitles"


@dataclass(frozen=True)
class SearchSlice:
    """One scientistSearchData filter combo."""

    domains: tuple[str, ...]
    disciplines: tuple[str, ...]
    degree_title: Optional[str]


def taxonomy_code_for_search(code: str) -> str:
    """Ludzie search filters usually use trailing N on DZ…/DS… codes from findDomains."""
    c = str(code).strip().upper().rstrip("N")
    if re.match(r"^(DZ|DS)\d{2,}$", c):
        return f"{c}N"
    return str(code).strip()


def fetch_find_domains(client: HttpClient, year: int) -> Any:
    return client.get_json(_FIND_DOMAINS, params={"year": year})


def fetch_degree_codes(client: HttpClient) -> list[str]:
    raw = client.get_json(_DEGREE_TITLES)
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, dict) and x.get("code"):
            out.append(str(x["code"]).strip())
    return out


def iter_slices_from_dictionary(
    client: HttpClient,
    *,
    year: int,
    filter_domains: Optional[list[str]] = None,
    filter_disciplines: Optional[list[str]] = None,
    filter_degrees: Optional[list[str]] = None,
    max_slices: Optional[int] = None,
) -> list[SearchSlice]:
    """Cartesian (each domain–discipline leaf) × degreeTitles."""
    data = fetch_find_domains(client, year)
    codes = fetch_degree_codes(client)
    if filter_degrees:
        allowed = {x.strip().upper() for x in filter_degrees}
        codes = [c for c in codes if c.upper() in allowed]

    fd: Optional[set[str]] = None
    if filter_domains:
        fd = {taxonomy_code_for_search(x) for x in filter_domains if x and str(x).strip()}
    fdis: Optional[set[str]] = None
    if filter_disciplines:
        fdis = {taxonomy_code_for_search(x) for x in filter_disciplines if x and str(x).strip()}

    out: list[SearchSlice] = []
    if not isinstance(data, list):
        return out
    for row in data:
        if not isinstance(row, dict):
            continue
        dom = row.get("domain") or {}
        dcode_raw = dom.get("code")
        if not dcode_raw:
            continue
        d_search = taxonomy_code_for_search(str(dcode_raw))
        if fd is not None and d_search not in fd:
            continue
        for disc in row.get("disciplines") or []:
            if not isinstance(disc, dict):
                continue
            sc = disc.get("code")
            if not sc:
                continue
            disc_search = taxonomy_code_for_search(str(sc))
            if fdis is not None and disc_search not in fdis:
                continue
            for deg in codes:
                out.append(
                    SearchSlice(
                        domains=(d_search,),
                        disciplines=(disc_search,),
                        degree_title=deg,
                    )
                )
                if max_slices is not None and len(out) >= max_slices:
                    return out
    return out


def manual_slices(
    domains: Optional[list[str]],
    disciplines: Optional[list[str]],
    *,
    degrees: Optional[list[str]],
) -> list[SearchSlice]:
    """Manual CLI: omit degreeTitles when degrees list empty."""
    dom_t = tuple(str(x).strip() for x in (domains or []) if x and str(x).strip())
    dis_t = tuple(str(x).strip() for x in (disciplines or []) if x and str(x).strip())
    deg_list = [str(x).strip() for x in (degrees or []) if x and str(x).strip()]
    if not deg_list:
        return [SearchSlice(domains=dom_t, disciplines=dis_t, degree_title=None)]
    return [SearchSlice(domains=dom_t, disciplines=dis_t, degree_title=d) for d in deg_list]
