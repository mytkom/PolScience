from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ludzie_nauki import db
from ludzie_nauki.http_client import HttpClient
from ludzie_nauki.util import main_localized_value, project_author_display_name


def _ensure_stub(conn, author: dict[str, Any]) -> None:
    pid = author.get("profileId")
    if not pid:
        return
    display = project_author_display_name(author)
    conn.execute(
        """
        INSERT OR IGNORE INTO profiles (id, given_name, is_stub)
        VALUES (?, ?, 1)
        """,
        (pid, display),
    )


def _paginate_content(
    client: HttpClient,
    path: str,
    *,
    page_size: int,
    params: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    page = 0
    rows: list[dict[str, Any]] = []
    base_params = dict(params or {})
    while True:
        payload = client.get_json(
            path,
            params={**base_params, "page": page, "size": page_size},
        )
        if not isinstance(payload, dict):
            break
        block = payload.get("content") or []
        if not block:
            break
        rows.extend(block)
        total = int(payload.get("total") or 0)
        psize = int((payload.get("pageable") or {}).get("pageSize") or page_size)
        if total and (page + 1) * psize >= total:
            break
        if len(block) < psize:
            break
        page += 1
    return rows


def _roles_json(author: dict[str, Any]) -> str | None:
    roles = author.get("authorRoles")
    if not roles:
        return None
    if isinstance(roles, list):
        return json.dumps(roles, ensure_ascii=False)
    return str(roles)


def _apply_project_detail(conn, detail: dict[str, Any]) -> None:
    project_id = detail.get("projectId")
    if not project_id:
        return
    title = main_localized_value(detail.get("projectTitles"))
    abstract = main_localized_value(detail.get("abstracts"))
    funds = detail.get("funds")
    if funds is not None:
        try:
            funds = float(funds)
        except (TypeError, ValueError):
            funds = None
    db.upsert_project_minimal(
        conn,
        project_id,
        title=title or detail.get("projectTitle"),
        project_number=detail.get("projectNumber"),
        classification=detail.get("projectClassification"),
        start_date=detail.get("startDate"),
        end_date=detail.get("endDate"),
        funds=funds,
        project_source=detail.get("projectSource"),
        edition=detail.get("edition"),
        abstract=abstract,
        link_radon=detail.get("linkRadon"),
        entity_showing_uuid=detail.get("entityShowingAchievementsUuid"),
        entity_showing_name=detail.get("entityShowingAchievementsName"),
    )
    keywords = [str(k).strip() for k in (detail.get("keyWords") or []) if k and str(k).strip()]
    db.replace_project_keywords(conn, project_id, keywords)
    financing = [
        str(n).strip() for n in (detail.get("financingInstitutions") or []) if n and str(n).strip()
    ]
    db.replace_project_financing(conn, project_id, financing)
    impl_rows: list[tuple[str | None, str, bool]] = []
    for inst in detail.get("implementingInstitutions") or []:
        if not isinstance(inst, dict):
            continue
        name = (inst.get("name") or "").strip()
        if not name:
            continue
        uuid = (inst.get("uuid") or "").strip() or None
        is_leader = str(inst.get("leader") or "0") == "1"
        impl_rows.append((uuid, name, is_leader))
    db.replace_project_implementing(conn, project_id, impl_rows)
    for mgr in detail.get("projectManagers") or []:
        if not isinstance(mgr, dict):
            continue
        mid = (mgr.get("idn") or "").strip()
        if not mid:
            continue
        parts = [mgr.get("firstName"), mgr.get("middleName"), mgr.get("lastName")]
        display = " ".join(str(p).strip() for p in parts if p) or mid
        conn.execute(
            """
            INSERT OR IGNORE INTO profiles (id, given_name, is_stub)
            VALUES (?, ?, 1)
            """,
            (mid, display),
        )
    db.set_project_detail_fetched(conn, project_id, True)


def _ingest_project_for_profile(
    conn,
    client: HttpClient,
    profile_id: str,
    row: dict[str, Any],
    *,
    author_page_size: int,
) -> None:
    project_id = row.get("projectId")
    if not project_id:
        return
    funds = row.get("funds")
    if funds is not None:
        try:
            funds = float(funds)
        except (TypeError, ValueError):
            funds = None
    db.upsert_project_minimal(
        conn,
        project_id,
        title=row.get("projectTitle"),
        classification=row.get("projectClassification"),
        start_date=row.get("startDate"),
        end_date=row.get("endDate"),
        funds=funds,
        project_source=row.get("projectSource"),
    )
    db.insert_profile_project(conn, profile_id, project_id)

    if not db.project_detail_fetched(conn, project_id):
        detail = client.get_json(f"/v1.0/public/{profile_id}/projects/{project_id}")
        if isinstance(detail, dict):
            _apply_project_detail(conn, detail)
        else:
            db.set_project_detail_fetched(conn, project_id, True)

    authors = _paginate_content(
        client,
        f"/v1.0/public/{profile_id}/projects/{project_id}/authors",
        page_size=author_page_size,
    )
    for au in authors:
        aid = au.get("profileId")
        if not aid:
            continue
        _ensure_stub(conn, au)
        db.insert_profile_project(conn, aid, project_id, roles=_roles_json(au))


def _apply_patent_detail(conn, patent_id: str, detail: dict[str, Any]) -> None:
    ipd = detail.get("industrialPropertyDetails") or {}
    title = ipd.get("calculatedTitle") or main_localized_value(ipd.get("titles"))
    abstract = main_localized_value(ipd.get("abstracts"))
    db.upsert_patent_minimal(
        conn,
        patent_id,
        title=title,
        type_code=ipd.get("typeCode"),
        type_label=ipd.get("typeName"),
        abstract=abstract,
        calculated_language_code=ipd.get("calculatedLanguageCode"),
        patent_source=detail.get("patenSource") or detail.get("patentSource"),
    )
    for right in detail.get("industrialPropertyRights") or []:
        if not isinstance(right, dict):
            continue
        right_id = right.get("industrialPropertyRightId")
        if not right_id:
            continue
        esd = right.get("entityShowingData") or {}
        db.upsert_patent_right(
            conn,
            right_id,
            patent_id,
            application_date=right.get("applicationDate"),
            application_number=right.get("applicationNumber"),
            publication_date=right.get("publicationDate"),
            publication_number=right.get("publicationNumber"),
            granting_institution_code=right.get("grantingInstitutionCode"),
            granting_institution_name=right.get("grantingInstitutionName"),
            granting_institution_country=right.get("grantingInstitutionCountry"),
            protection_region_code=right.get("protectionRegionCode"),
            protection_region_name=right.get("protectionRegionName"),
            priority_region=right.get("priorityRegion"),
            priority_number=right.get("priorityNumber"),
            link_radon=right.get("linkRadon"),
            link_uprp=right.get("linkUprp"),
            link_espacenet=right.get("linkEspacenet"),
            entity_showing_id=esd.get("entityShowingDataId"),
            entity_showing_name=esd.get("entityShowingDataName"),
        )
    db.set_patent_detail_fetched(conn, patent_id, True)


def _ingest_patent_for_profile(
    conn,
    client: HttpClient,
    profile_id: str,
    row: dict[str, Any],
    *,
    author_page_size: int,
) -> None:
    patent_id = row.get("industrialPropertyId")
    if not patent_id:
        return
    db.upsert_patent_minimal(
        conn,
        patent_id,
        title=row.get("calculatedTitle"),
        type_code=row.get("typeCode"),
        type_label=row.get("typeLabel"),
        patent_source=row.get("patenSource") or row.get("patentSource"),
    )
    db.insert_profile_patent(conn, profile_id, patent_id)

    if not db.patent_detail_fetched(conn, patent_id):
        detail = client.get_json(f"/v1.0/public/{profile_id}/patents/{patent_id}")
        if isinstance(detail, dict):
            _apply_patent_detail(conn, patent_id, detail)
        else:
            db.set_patent_detail_fetched(conn, patent_id, True)

    right_ids = db.list_patent_right_ids(conn, patent_id)
    for right_id in right_ids:
        authors = _paginate_content(
            client,
            (
                f"/v1.0/public/{profile_id}/industrialProperty/{patent_id}"
                f"/industrialPropertyRight/{right_id}/authors"
            ),
            page_size=author_page_size,
        )
        for au in authors:
            aid = au.get("profileId")
            if not aid:
                continue
            _ensure_stub(conn, au)
            db.insert_patent_right_authorship(conn, aid, right_id)


def _ingest_projects_for_profile(
    conn,
    client: HttpClient,
    profile_id: str,
    *,
    page_size: int,
    author_page_size: int,
) -> None:
    page = 0
    total = None
    while True:
        payload = client.get_json(
            f"/v1.0/public/{profile_id}/projects",
            params={"page": page, "size": page_size, "sort": "startDate,DESC"},
        )
        if not isinstance(payload, dict):
            break
        rows = payload.get("content") or []
        if total is None:
            total = int(payload.get("total") or 0)
        if not rows:
            break
        for row in rows:
            _ingest_project_for_profile(
                conn, client, profile_id, row, author_page_size=author_page_size
            )
        psize = int((payload.get("pageable") or {}).get("pageSize") or page_size)
        if total and (page + 1) * psize >= total:
            break
        if len(rows) < psize:
            break
        page += 1


def _ingest_patents_for_profile(
    conn,
    client: HttpClient,
    profile_id: str,
    *,
    page_size: int,
    author_page_size: int,
) -> None:
    page = 0
    total = None
    while True:
        payload = client.get_json(
            f"/v1.0/public/{profile_id}/patents",
            params={"page": page, "size": page_size, "sort": "calculatedTitle,DESC"},
        )
        if not isinstance(payload, dict):
            break
        rows = payload.get("content") or []
        if total is None:
            total = int(payload.get("total") or 0)
        if not rows:
            break
        for row in rows:
            _ingest_patent_for_profile(
                conn, client, profile_id, row, author_page_size=author_page_size
            )
        psize = int((payload.get("pageable") or {}).get("pageSize") or page_size)
        if total and (page + 1) * psize >= total:
            break
        if len(rows) < psize:
            break
        page += 1


def run_pass4(
    conn,
    client: HttpClient,
    *,
    domain_codes: Optional[list[str]] = None,
    discipline_codes: Optional[list[str]] = None,
    project_page_size: int = 500,
    patent_page_size: int = 500,
    author_page_size: int = 40,
    single_profile_id: Optional[str] = None,
    progress: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> int:
    """Project + patent ingestion for profiles. Returns profile count processed."""
    if single_profile_id:
        ids = [single_profile_id]
    else:
        ids = db.profile_ids_for_pass4(
            conn, domain_codes=domain_codes, discipline_codes=discipline_codes
        )
    done = 0
    for pid in ids:
        _ingest_projects_for_profile(
            conn,
            client,
            pid,
            page_size=project_page_size,
            author_page_size=author_page_size,
        )
        _ingest_patents_for_profile(
            conn,
            client,
            pid,
            page_size=patent_page_size,
            author_page_size=author_page_size,
        )
        done += 1
        if progress:
            progress(pid, {"profiles_done": done, "of": len(ids)})
    return done
