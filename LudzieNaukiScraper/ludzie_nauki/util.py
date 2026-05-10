from __future__ import annotations

from typing import Any, Optional

# Prefer academic title / degree rank (lower = stronger).
_DEGREE_RANK: dict[str, int] = {
    "PROF": 0,
    "DR_HAB": 1,
    "DRHAB": 1,
    "DR": 2,
    "MGR": 3,
    "INZ": 4,
    "LIC": 5,
}


def normalize_degree_code(code: str) -> str:
    c = code.strip().upper()
    if c == "DRHAB":
        return "DR_HAB"
    return c


def pick_primary_degree_code(items: list[dict[str, Any]] | None) -> Optional[str]:
    if not items:
        return None
    best_code: Optional[str] = None
    best_rank = 999
    best_year = -1
    for it in items:
        dt = it.get("degreeOrTitleType") or {}
        raw = dt.get("code")
        if not raw:
            continue
        code = normalize_degree_code(raw)
        rank = _DEGREE_RANK.get(code, 99)
        year = int(it.get("year") or 0)
        if rank < best_rank or (rank == best_rank and year > best_year):
            best_rank = rank
            best_year = year
            best_code = code
    return best_code


def display_name_from_details(dp: dict[str, Any]) -> str:
    """Full display name from detailsPerson (English request)."""
    parts = [dp.get("prefix"), dp.get("name"), dp.get("secondName"), dp.get("surname")]
    out = " ".join(str(p).strip() for p in parts if p)
    return out or "unknown"


def build_profile_name(row: dict[str, Any]) -> str:
    parts: list[str] = []
    t = row.get("title")
    if t:
        parts.append(str(t).strip())
    first = row.get("firstName")
    second = row.get("secondName")
    prefix = row.get("prefix")
    sur = row.get("surname")
    for p in (prefix, first, second, sur):
        if p:
            parts.append(str(p).strip())
    if parts:
        return " ".join(parts)
    return row.get("profileId") or "unknown"


def author_display_name(author: dict[str, Any]) -> str:
    parts = [author.get("prefix"), author.get("name"), author.get("secondName"), author.get("surname")]
    out = " ".join(str(p).strip() for p in parts if p)
    return out or (author.get("profileId") or "unknown")


def extract_journal_from_detail(detail: dict[str, Any]) -> Optional[str]:
    # Prefer human-readable venue strings from typed source blocks.
    for key in ("articleSource", "bookSource", "chapterSource", "conferenceSource", "editBookSource"):
        block = detail.get(key)
        if not block:
            continue
        if isinstance(block, dict):
            for sub in ("journalTitle", "bookTitle", "seriesTitle", "sourceTitle", "conferenceName"):
                v = block.get(sub)
                if v:
                    return str(v)
        elif isinstance(block, list) and block:
            first = block[0]
            if isinstance(first, dict):
                for sub in ("journalTitle", "bookTitle", "seriesTitle"):
                    v = first.get(sub)
                    if v:
                        return str(v)
    art = detail.get("articleSource")
    if isinstance(art, list) and art and isinstance(art[0], str):
        return art[0]
    bs = detail.get("bookSource")
    if isinstance(bs, list) and bs and isinstance(bs[0], str):
        return bs[0]
    return None


def pages_from_detail(detail: dict[str, Any]) -> Optional[str]:
    det = detail.get("details") or {}
    pf, pt = det.get("pageFrom"), det.get("pageTo")
    pn = det.get("pageNumber")
    if pf is not None and pt is not None:
        return f"{pf}-{pt}"
    if pn is not None:
        return str(pn)
    return None


def _is_title_english(block: dict[str, Any]) -> bool:
    lc = (block.get("languageCode") or "").strip().lower()
    if lc in ("eng", "en"):
        return True
    lb = (block.get("label") or "").strip().lower()
    return "angiel" in lb


def _is_title_polish(block: dict[str, Any]) -> bool:
    lc = (block.get("languageCode") or "").strip().lower()
    if lc in ("pol", "pl"):
        return True
    lb = (block.get("label") or "").strip().lower()
    return lb == "polski"


def main_title(detail: dict[str, Any]) -> Optional[str]:
    """Pick one title: English first, else Polish, else first non-empty entry."""
    raw = detail.get("titles")
    if not raw or not isinstance(raw, list):
        return None
    entries: list[tuple[str, dict[str, Any]]] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        tit = t.get("title")
        if tit is None or not str(tit).strip():
            continue
        entries.append((str(tit).strip(), t))
    if not entries:
        return None
    for title, block in entries:
        if _is_title_english(block):
            return title
    for title, block in entries:
        if _is_title_polish(block):
            return title
    return entries[0][0]


def main_abstract(detail: dict[str, Any]) -> Optional[str]:
    """Pick one abstract from abstractDocuments: English first, else Polish, else first non-empty."""
    raw = detail.get("abstractDocuments")
    if not raw or not isinstance(raw, list):
        return None
    entries: list[tuple[str, dict[str, Any]]] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        ab = t.get("abstract")
        if ab is None or not str(ab).strip():
            continue
        entries.append((str(ab).strip(), t))
    if not entries:
        return None
    for text, block in entries:
        if _is_title_english(block):
            return text
    for text, block in entries:
        if _is_title_polish(block):
            return text
    return entries[0][0]
