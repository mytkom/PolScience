from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

from ludzie_nauki import db
from ludzie_nauki.http_client import HttpClient, RadonClient, stable_org_id
from ludzie_nauki.search_sharding import SearchSlice, iter_slices_from_dictionary, manual_slices
from ludzie_nauki.util import build_profile_name, display_name_from_details, pick_primary_degree_code

LOG = logging.getLogger(__name__)

_DETAILS_PERSON = "/v1.3/public/profile/{pid}/detailsPerson"
_SEARCH = "/v1.1/public/profile/scientistSearchData"

_TWIN_SURNAME_SORTS = ("surname,ASC", "surname,DESC")
_DEFAULT_PER_SORT_ROW_CAP = 1000
_TOTAL_HITS_WARN_THRESHOLD = 2000


def _slice_label(sl: SearchSlice) -> str:
    return (
        f"domains={','.join(sl.domains) if sl.domains else '*'}|"
        f"disciplines={','.join(sl.disciplines) if sl.disciplines else '*'}|"
        f"degree={sl.degree_title or '-'}"
    )


def scientist_search_params(
    *,
    page: int,
    size: int,
    domains: Optional[list[str]] = None,
    disciplines: Optional[list[str]] = None,
    degree_title: Optional[str] = None,
    sort: Optional[str] = None,
    institution_id: Optional[str] = None,
) -> list[tuple[str, Any]]:
    """Query string for scientistSearchData; repeated domains=/disciplines= when needed."""
    pairs: list[tuple[str, Any]] = [
        ("page", page),
        ("size", size),
        ("fullQuery", " "),
    ]
    for code in domains or []:
        s = str(code).strip()
        if s:
            pairs.append(("domains", s))
    for code in disciplines or []:
        s = str(code).strip()
        if s:
            pairs.append(("disciplines", s))
    if degree_title and str(degree_title).strip():
        pairs.append(("degreeTitles", str(degree_title).strip()))
    if sort and str(sort).strip():
        pairs.append(("sort", str(sort).strip()))
    inst = (institution_id or "").strip()
    if inst:
        pairs.append(("institutionId", inst))
    return pairs


def _normalized_domain_discipline_lists(
    domains: Optional[list[str]],
    disciplines: Optional[list[str]],
) -> tuple[list[str], list[str]]:
    dom = [str(x).strip() for x in (domains or []) if x and str(x).strip()]
    dis = [str(x).strip() for x in (disciplines or []) if x and str(x).strip()]
    return dom, dis


def _fetch_enrichment_bundle(client: HttpClient, profile_id: str) -> dict[str, Any]:
    orcid = client.get_json(f"/v1.0/public/profile/{profile_id}/orcid")
    kws = client.get_json(f"/v1.0/public/profile/{profile_id}/keyWords")
    mem = client.get_json(f"/v1.1/public/{profile_id}/memberships")
    fn = client.get_json(f"/v1.1/public/{profile_id}/functions")
    deg = client.get_json(f"/v1.0/public/profile/{profile_id}/degreesAndTitles")
    path = _DETAILS_PERSON.format(pid=profile_id)
    dp_en = client.get_json(path)
    dp_pl = client.get_json(path, extra_headers={"Accept-Language": "pl-PL"})
    return {
        "orcid_payload": orcid,
        "keywords_raw": kws,
        "memberships_raw": mem,
        "functions_raw": fn,
        "degrees_raw": deg,
        "details_person_en": dp_en,
        "details_person_pl": dp_pl,
    }


def _normalize_keywords_summary(raw: Any) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    if not isinstance(raw, list):
        return out
    for it in raw:
        if isinstance(it, dict) and it.get("keyword"):
            out.append((str(it["keyword"]), int(it.get("count") or 1)))
    return out


def _apply_domain_discipline_labels(conn, dp: Any, *, lang: str) -> None:
    if not isinstance(dp, dict):
        return
    for item in dp.get("domainDisciplines") or []:
        dom = item.get("domain") or {}
        disc = item.get("discipline") or {}
        dcode, dlab = dom.get("code"), dom.get("label")
        ccode, clab = disc.get("code"), disc.get("label")
        if dcode:
            if lang == "en":
                db.upsert_scientific_domain(conn, dcode, label_en=dlab)
            else:
                db.upsert_scientific_domain(conn, dcode, label_pl=dlab)
        if ccode and dcode:
            if lang == "en":
                db.upsert_scientific_domain(conn, ccode, label_en=clab, parent_code=dcode)
            else:
                db.upsert_scientific_domain(conn, ccode, label_pl=clab, parent_code=dcode)


def _ingest_employments(
    conn,
    radon: Optional[RadonClient],
    profile_id: str,
    dp_en: dict[str, Any],
    *,
    radon_defer: bool = False,
) -> None:
    for emp in dp_en.get("employments") or []:
        inst = emp.get("institution") or {}
        iid = inst.get("id")
        if not iid:
            continue
        ludzie_id = str(iid)
        ludzie_nm = str(inst.get("initialName") or inst.get("name") or "unknown")
        if radon_defer:
            db.enqueue_radon_task(conn, ludzie_id, ludzie_nm)
            radon_payload = None
        else:
            radon_payload = radon.portal_search_institution(ludzie_id) if radon else None
        db.upsert_institution_from_radon_payload(conn, radon_payload, ludzie_id=ludzie_id, ludzie_name=ludzie_nm)
        db.insert_profile_employment(conn, profile_id, emp, ludzie_id)

    for ce in dp_en.get("currentEmployments") or []:
        inst = ce.get("institution") or {}
        iid = inst.get("id")
        if not iid:
            continue
        ludzie_id = str(iid)
        if db.profile_has_current_employment_at(conn, profile_id, ludzie_id):
            continue
        ludzie_nm = str(inst.get("name") or "unknown")
        if radon_defer:
            db.enqueue_radon_task(conn, ludzie_id, ludzie_nm)
            radon_payload = None
        else:
            radon_payload = radon.portal_search_institution(ludzie_id) if radon else None
        db.upsert_institution_from_radon_payload(conn, radon_payload, ludzie_id=ludzie_id, ludzie_name=ludzie_nm)
        synthetic = {
            "employmentId": f"current:{profile_id}:{ludzie_id}",
            "startDate": None,
            "endDate": None,
            "statusEmployment": "CURRENT",
            "institution": inst,
            "internetLink": None,
            "additionalInformation": None,
            "employmentSource": "CURRENT_EMPLOYMENT",
        }
        db.insert_profile_employment(conn, profile_id, synthetic, ludzie_id)


def _apply_enrichment(
    conn,
    profile_id: str,
    search_row: dict[str, Any],
    bundle: dict[str, Any],
    radon_client: Optional[RadonClient] = None,
    *,
    radon_defer: bool = False,
) -> None:
    dp_en = bundle.get("details_person_en")
    dp_pl = bundle.get("details_person_pl")

    _apply_domain_discipline_labels(conn, dp_en, lang="en")
    _apply_domain_discipline_labels(conn, dp_pl, lang="pl")

    deg_items: list[dict[str, Any]] = []
    raw_deg = bundle.get("degrees_raw")
    if isinstance(raw_deg, dict):
        deg_items = list(raw_deg.get("items") or [])
    for it in deg_items:
        dt = it.get("degreeOrTitleType") or {}
        if dt.get("code"):
            db.ensure_degree_title(conn, dt["code"], dt.get("label"))
        for lbl in it.get("classificationLabels") or []:
            dom = lbl.get("domain") or {}
            disc = lbl.get("discipline") or {}
            dcode, dlab = dom.get("code"), dom.get("label")
            ccode, clab = disc.get("code"), disc.get("label")
            if dcode:
                db.upsert_scientific_domain(conn, dcode, label_en=dlab)
            if ccode and dcode:
                db.upsert_scientific_domain(conn, ccode, label_en=clab, parent_code=dcode)

    degree_code = pick_primary_degree_code(deg_items)

    orcid_val = None
    op = bundle.get("orcid_payload")
    if isinstance(op, dict):
        orcid_val = op.get("orcid")

    if isinstance(dp_en, dict):
        given = (str(dp_en.get("name") or "").strip())
        surname_val = (str(dp_en.get("surname") or "").strip() if dp_en.get("surname") else None)
        given_primary = given or display_name_from_details(dp_en) or None
        db.upsert_profile(
            conn,
            profile_id,
            given_name=given_primary or "unknown",
            surname=surname_val,
            prefix=(str(dp_en["prefix"]).strip() if dp_en.get("prefix") else None),
            second_name=(str(dp_en["secondName"]).strip() if dp_en.get("secondName") else None),
            calculated_edu_level=(
                str(dp_en["calculatedEduLevel"]).strip() if dp_en.get("calculatedEduLevel") else None
            ),
            about_me_pl=(str(dp_pl["aboutMe"]).strip() if isinstance(dp_pl, dict) and dp_pl.get("aboutMe") else None),
            about_me_en=(str(dp_en["aboutMeEn"]).strip() if dp_en.get("aboutMeEn") else None),
            orcid=orcid_val,
            degree_code=degree_code,
            domain_code=(
                (str(dp_en["domainIconCode"]).strip() if dp_en.get("domainIconCode") else None)
                or search_row.get("domainCode")
            ),
            is_stub=0,
        )
    else:
        fn = (str(search_row.get("firstName") or "").strip())
        sn = (str(search_row.get("surname") or "").strip())
        given_primary = fn or build_profile_name(search_row) or None
        db.upsert_profile(
            conn,
            profile_id,
            given_name=given_primary or "unknown",
            surname=sn or None,
            prefix=(str(search_row["prefix"]).strip() if search_row.get("prefix") else None),
            second_name=(str(search_row["secondName"]).strip() if search_row.get("secondName") else None),
            calculated_edu_level=None,
            about_me_pl=None,
            about_me_en=None,
            orcid=orcid_val,
            degree_code=degree_code,
            domain_code=search_row.get("domainCode"),
            is_stub=0,
        )
        dp_en = None

    db.delete_child_rows_for_profile(conn, profile_id)

    if isinstance(dp_en, dict):
        _ingest_employments(conn, radon_client, profile_id, dp_en, radon_defer=radon_defer)
        for item in dp_en.get("domainDisciplines") or []:
            dom = item.get("domain") or {}
            disc = item.get("discipline") or {}
            dc, cc = dom.get("code"), disc.get("code")
            if dc and cc:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO profile_domain_disciplines (profile_id, domain_code, discipline_code)
                    VALUES (?, ?, ?)
                    """,
                    (profile_id, dc, cc),
                )
        for sp in dp_en.get("specialties") or []:
            sid = sp.get("specialtyId")
            if not sid:
                continue
            conn.execute(
                """
                INSERT INTO specialties (id, label_pl, label_en)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  label_pl = COALESCE(excluded.label_pl, specialties.label_pl),
                  label_en = COALESCE(excluded.label_en, specialties.label_en)
                """,
                (sid, sp.get("labelPl"), sp.get("labelEn")),
            )
            conn.execute(
                """
                INSERT INTO profile_specialties (profile_id, specialty_id, sort_order)
                VALUES (?, ?, ?)
                ON CONFLICT(profile_id, specialty_id) DO UPDATE SET
                  sort_order = excluded.sort_order
                """,
                (profile_id, sid, int(sp.get("order") or 0)),
            )

    kws = _normalize_keywords_summary(bundle.get("keywords_raw"))
    db.replace_profile_summary_keywords(conn, profile_id, kws)

    mem_block = bundle.get("memberships_raw")
    if isinstance(mem_block, dict):
        for m in mem_block.get("memberships") or []:
            label = m.get("gremiumName") or m.get("organizationStructure") or "unknown"
            oid = m.get("gremiumId") or stable_org_id(str(label))
            db.insert_organization(conn, oid, str(label)[:2000])
            role = m.get("memberKind")
            terms = m.get("terms") or []
            if not terms:
                conn.execute(
                    """
                    INSERT INTO profile_memberships (profile_id, org_id, role, start_date, end_date)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (profile_id, oid, role, None, None),
                )
            else:
                for t in terms:
                    start = t.get("from")
                    end = t.get("to")
                    conn.execute(
                        """
                        INSERT INTO profile_memberships (profile_id, org_id, role, start_date, end_date)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            profile_id,
                            oid,
                            role,
                            int(start) if start is not None else None,
                            int(end) if end is not None else None,
                        ),
                    )

    fn_block = bundle.get("functions_raw")
    if isinstance(fn_block, dict):
        for fn in fn_block.get("functions") or []:
            label = fn.get("gremiumName") or fn.get("structure") or "unknown"
            oid = fn.get("gremiumId") or stable_org_id(str(label))
            db.insert_organization(conn, oid, str(label)[:2000])
            fname = fn.get("gremiumFunction") or "function"
            conn.execute(
                """
                INSERT INTO profile_functions (profile_id, org_id, function_name, start_date, end_date)
                VALUES (?, ?, ?, ?, ?)
                """,
                (profile_id, oid, str(fname), None, None),
            )


def _flush_batch(
    conn,
    client: HttpClient,
    radon_client: Optional[RadonClient],
    batch: list[tuple[str, dict[str, Any]]],
    concurrency: int,
    *,
    radon_defer: bool = False,
) -> None:
    if not batch:
        return
    if concurrency <= 1:
        for pid, row in batch:
            bundle = _fetch_enrichment_bundle(client, pid)
            _apply_enrichment(conn, pid, row, bundle, radon_client, radon_defer=radon_defer)
        return
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(_fetch_enrichment_bundle, client, pid): (pid, row) for pid, row in batch}
        for fut in as_completed(futs):
            pid, row = futs[fut]
            bundle = fut.result()
            _apply_enrichment(conn, pid, row, bundle, radon_client, radon_defer=radon_defer)


def run_pass1_single_profile(
    conn,
    client: HttpClient,
    profile_id: str,
    radon_client: Optional[RadonClient] = None,
    *,
    radon_defer: bool = True,
    search_domains: Optional[list[str]] = None,
    search_disciplines: Optional[list[str]] = None,
) -> int:
    """Enrich one profile without scientistSearchData crawl (quick smoke test)."""
    pid = str(profile_id).strip()
    if db.profile_exists(conn, pid):
        LOG.info("skip pass1 enrichment: %s already in DB", pid)
        return 0
    dom, dis = _normalized_domain_discipline_lists(search_domains, search_disciplines)
    if dis and not dom:
        raise ValueError("discipline filter requires at least one domain")
    seed = client.get_json(
        _SEARCH,
        params=scientist_search_params(page=0, size=1, domains=dom if dom else None, disciplines=dis if dis else None),
    )
    if isinstance(seed, dict):
        db.seed_dictionaries(conn, seed.get("dictionaries") or {})
    search_row: dict[str, Any] = {
        "profileId": pid,
        "firstName": None,
        "surname": None,
        "secondName": None,
        "prefix": None,
        "title": None,
        "domainCode": None,
    }
    bundle = _fetch_enrichment_bundle(client, pid)
    _apply_enrichment(conn, pid, search_row, bundle, radon_client, radon_defer=radon_defer)
    return 1


def run_pass1(
    conn,
    client: HttpClient,
    *,
    radon_client: Optional[RadonClient] = None,
    radon_defer: bool = True,
    page_size: int = 1000,
    search_domains: Optional[list[str]] = None,
    search_disciplines: Optional[list[str]] = None,
    search_degree_titles: Optional[list[str]] = None,
    shard_crawl: bool = True,
    dictionary_year: int = 2020,
    max_shards: Optional[int] = None,
    per_sort_row_cap: int = _DEFAULT_PER_SORT_ROW_CAP,
    max_profiles: Optional[int] = None,
    concurrency: int = 4,
    progress: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> int:
    """scientistSearchData slices with twin surname sorts; dedupe IDs. Slices with totalHits over the cap get a follow-up pass with institutionId per row in institutions."""
    dom, dis = _normalized_domain_discipline_lists(search_domains, search_disciplines)
    if dis and not dom and not shard_crawl:
        raise ValueError("discipline filter requires at least one domain (unless dictionary shard crawl is enabled)")
    if shard_crawl:
        slices = iter_slices_from_dictionary(
            client,
            year=dictionary_year,
            filter_domains=list(dom) if dom else None,
            filter_disciplines=list(dis) if dis else None,
            filter_degrees=search_degree_titles,
            max_slices=max_shards,
        )
    else:
        slices = manual_slices(dom or None, dis or None, degrees=search_degree_titles)
    if not slices:
        LOG.error("Pass1: empty search slice list")
        return 0
    LOG.info(
        "Pass1 %s slice(s)%s",
        len(slices),
        " shard-crawl" if shard_crawl else "",
    )

    enriched = 0
    batch: list[tuple[str, dict[str, Any]]] = []
    batch_cap = max(8, concurrency * 4)
    seen: set[str] = set()

    def flush_pending() -> None:
        nonlocal enriched, batch
        if not batch:
            return
        if max_profiles is not None:
            room = max_profiles - enriched
            if room <= 0:
                batch = []
                return
            if len(batch) > room:
                batch = batch[:room]
        last_pid = batch[-1][0]
        n = len(batch)
        _flush_batch(conn, client, radon_client, batch, concurrency, radon_defer=radon_defer)
        enriched += n
        batch = []
        if progress:
            progress(last_pid, {"enriched": enriched})

    overflow_slices: list[SearchSlice] = []
    overflow_seen: set[SearchSlice] = set()

    def crawl_slice(
        sl: SearchSlice,
        *,
        slice_tag: str,
        institution_id: Optional[str],
        capture_overflow_without_institution: bool,
    ) -> bool:
        """Return True if Pass 1 should stop early (max_profiles)."""
        nonlocal enriched, batch
        hit_totals_logged = False
        domains_arg = list(sl.domains) if sl.domains else None
        dis_arg = list(sl.disciplines) if sl.disciplines else None
        degree_arg = sl.degree_title
        inst = (institution_id or "").strip() or None

        def ctx() -> str:
            lab = _slice_label(sl)
            return f"{lab}; institutionId={inst}" if inst else lab

        for sort_key in _TWIN_SURNAME_SORTS:
            page = 0
            consumed_this_sort = 0
            while consumed_this_sort < per_sort_row_cap:
                if max_profiles is not None and enriched >= max_profiles:
                    flush_pending()
                    return True
                q = scientist_search_params(
                    page=page,
                    size=page_size,
                    domains=domains_arg,
                    disciplines=dis_arg,
                    degree_title=degree_arg,
                    sort=sort_key,
                    institution_id=inst,
                )
                payload = client.get_json(_SEARCH, params=q)
                if not isinstance(payload, dict):
                    LOG.warning("%s sort %s page %s invalid payload (%s)", slice_tag, sort_key, page, ctx())
                    break
                db.seed_dictionaries(conn, payload.get("dictionaries") or {})
                if not hit_totals_logged:
                    hit_totals_logged = True
                    th = int(payload.get("totalHits") or 0)
                    if th > _TOTAL_HITS_WARN_THRESHOLD:
                        suffix = (
                            "middle unreachable with surname ASC+DESC cap alone"
                            if inst is None
                            else "institution-filtered shard still oversized"
                        )
                        LOG.warning(
                            "%s [%s]: totalHits=%s > %s (%s)",
                            slice_tag,
                            ctx(),
                            th,
                            _TOTAL_HITS_WARN_THRESHOLD,
                            suffix,
                        )
                        if capture_overflow_without_institution and inst is None and sl not in overflow_seen:
                            overflow_seen.add(sl)
                            overflow_slices.append(sl)
                rows = (payload.get("page") or {}).get("content") or []
                if not rows:
                    break
                for row in rows:
                    if consumed_this_sort >= per_sort_row_cap:
                        break
                    consumed_this_sort += 1
                    pid = row.get("profileId")
                    if not pid:
                        continue
                    pid = str(pid)
                    if pid in seen:
                        continue
                    if db.profile_exists(conn, pid):
                        seen.add(pid)
                        continue
                    if max_profiles is not None and enriched + len(batch) >= max_profiles:
                        flush_pending()
                        return True
                    seen.add(pid)
                    batch.append((pid, row))
                    if len(batch) >= batch_cap:
                        flush_pending()
                if len(rows) < page_size:
                    break
                page += 1
            if max_profiles is not None and enriched >= max_profiles:
                flush_pending()
                return True
        return False

    slice_idx = 0
    for sl in slices:
        slice_idx += 1
        if crawl_slice(
            sl,
            slice_tag=f"slice #{slice_idx}",
            institution_id=None,
            capture_overflow_without_institution=True,
        ):
            return enriched

    flush_pending()

    inst_ids = db.list_institution_ids(conn)
    if overflow_slices:
        if not inst_ids:
            LOG.warning(
                "Pass1: %s oversized slice(s); institutions table empty — skip institution sub-crawl (populate institutions or rerun)",
                len(overflow_slices),
            )
        else:
            combos = len(overflow_slices) * len(inst_ids)
            LOG.info(
                "Pass1 institution sub-crawl: %s slice(s) × %s institution id(s) = %s combos",
                len(overflow_slices),
                len(inst_ids),
                combos,
            )
            oi = 0
            for sl in overflow_slices:
                for iid in inst_ids:
                    oi += 1
                    if crawl_slice(
                        sl,
                        slice_tag=f"overflow {oi}/{combos}",
                        institution_id=iid,
                        capture_overflow_without_institution=False,
                    ):
                        return enriched

    flush_pending()
    return enriched
