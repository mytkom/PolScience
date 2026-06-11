from __future__ import annotations

from typing import Any, Callable, Optional

from ludzie_nauki import db
from ludzie_nauki.http_client import HttpClient
from ludzie_nauki.util import (
    author_display_name,
    extract_journal_from_detail,
    main_abstract,
    main_title,
    pages_from_detail,
)


def _journal_from_list_row(pub: dict[str, Any]) -> Optional[str]:
    ps = pub.get("publicationSource") or []
    if ps and isinstance(ps[0], str):
        return ps[0]
    return None


def _iter_publication_kw_blocks(detail: dict[str, Any]):
    """Yield (term, language_code) from publication detail keyWords (multilingual blocks + legacy shapes)."""
    blocks = detail.get("keyWords")
    if blocks is None:
        return
    if not isinstance(blocks, list):
        return
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("keyWords"), list):
            lc = (block.get("languageCode") or block.get("language") or "").strip()
            for s in block["keyWords"]:
                if isinstance(s, str) and s.strip():
                    yield s.strip(), lc
        elif isinstance(block, str) and block.strip():
            yield block.strip(), ""
        elif isinstance(block, dict):
            kw = block.get("keyword") or block.get("term")
            if kw and str(kw).strip():
                yield str(kw).strip(), (block.get("languageCode") or block.get("language") or "").strip()


def _fetch_all_authors(client: HttpClient, owner_id: str, pub_id: str, page_size: int = 30) -> list[dict[str, Any]]:
    page = 0
    authors: list[dict[str, Any]] = []
    while True:
        payload = client.get_json(
            f"/v1.0/public/profile/{owner_id}/publication/{pub_id}/authors",
            params={"page": page, "size": page_size},
        )
        if not isinstance(payload, dict):
            break
        block = payload.get("content") or []
        if not block:
            break
        authors.extend(block)
        total = int(payload.get("total") or 0)
        psize = int((payload.get("pageable") or {}).get("pageSize") or page_size)
        if total and (page + 1) * psize >= total:
            break
        if len(block) < psize:
            break
        page += 1
    return authors


def _apply_detail_and_keywords(
    conn,
    profile_id: str,
    pub_id: str,
    detail: dict[str, Any],
) -> None:
    title = main_title(detail) or detail.get("title")
    abstract = main_abstract(detail)
    year = detail.get("year")
    doi = detail.get("doi")
    venue = extract_journal_from_detail(detail)
    pages = pages_from_detail(detail)
    ptype = detail.get("type") or detail.get("publicationTypeLabel")
    url = detail.get("url")
    db.upsert_publication_minimal(
        conn,
        pub_id,
        title=title,
        abstract=abstract,
        year=int(year) if year is not None else None,
        doi=doi,
        journal_name=venue,
        pages=pages,
        publication_type=str(ptype) if ptype else None,
        url=url,
    )
    for term, lang in _iter_publication_kw_blocks(detail):
        db.add_publication_extracted_term(conn, pub_id, term, lang)
    db.set_publication_detail_fetched(conn, pub_id, True)
    for term, lang in db.list_publication_extracted_terms(conn, pub_id):
        db.bump_extracted_keyword(conn, profile_id, term, lang, 1)


def _ensure_stub(conn, author: dict[str, Any]) -> None:
    pid = author.get("profileId")
    if not pid:
        return
    display = author_display_name(author)
    conn.execute(
        """
        INSERT OR IGNORE INTO profiles (id, given_name, is_stub)
        VALUES (?, ?, 1)
        """,
        (pid, display),
    )


def _ingest_publication_for_profile(
    conn,
    client: HttpClient,
    profile_id: str,
    pub: dict[str, Any],
) -> None:
    pub_id = pub.get("publicationId")
    if not pub_id:
        return
    title = pub.get("title")
    year = pub.get("year")
    doi = pub.get("doi")
    ptype = pub.get("publicationTypeLabel") or pub.get("publicationType")
    journal = _journal_from_list_row(pub)
    db.upsert_publication_minimal(
        conn,
        pub_id,
        title=title,
        year=int(year) if year is not None else None,
        doi=doi,
        journal_name=journal,
        pages=None,
        publication_type=str(ptype) if ptype else None,
        url=None,
    )
    db.insert_authorship(conn, profile_id, pub_id)

    if not db.publication_detail_fetched(conn, pub_id):
        detail = client.get_json(f"/v1.0/public/profile/{profile_id}/publication/{pub_id}")
        if isinstance(detail, dict):
            _apply_detail_and_keywords(conn, profile_id, pub_id, detail)
        else:
            db.set_publication_detail_fetched(conn, pub_id, True)
    else:
        for term, lang in db.list_publication_extracted_terms(conn, pub_id):
            db.bump_extracted_keyword(conn, profile_id, term, lang, 1)

    for au in _fetch_all_authors(client, profile_id, pub_id):
        aid = au.get("profileId")
        if not aid:
            continue
        _ensure_stub(conn, au)
        db.insert_authorship(conn, aid, pub_id)


def run_pass2(
    conn,
    client: HttpClient,
    *,
    domain_codes: Optional[list[str]] = None,
    discipline_codes: Optional[list[str]] = None,
    pub_page_size: int = 500,
    single_profile_id: Optional[str] = None,
    progress: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> int:
    """Publication ingestion for profiles. Returns profile count processed."""
    if single_profile_id:
        ids = [single_profile_id]
    else:
        ids = db.profile_ids_for_pass2(conn, domain_codes=domain_codes, discipline_codes=discipline_codes)
    done = 0
    for pid in ids:
        page = 0
        total = None
        while True:
            payload = client.get_json(
                f"/v1.0/public/publications/{pid}/publications",
                params={"page": page, "size": pub_page_size},
            )
            if not isinstance(payload, dict):
                break
            rows = payload.get("content") or []
            if total is None:
                total = int(payload.get("total") or 0)
            if not rows:
                break
            for pub in rows:
                _ingest_publication_for_profile(conn, client, pid, pub)
            psize = int((payload.get("pageable") or {}).get("pageSize") or pub_page_size)
            if total and (page + 1) * psize >= total:
                break
            if len(rows) < psize:
                break
            page += 1
        done += 1
        if progress:
            progress(pid, {"profiles_done": done, "of": len(ids)})
    return done
