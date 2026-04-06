from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup, Tag
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db_utils import ensure_dir, get_connection, json_dumps


BASE_URL = "https://ludzie.nauka.gov.pl"
RAW_HTML_DIR = "data/raw_html"
RAW_JSON_DIR = "data/raw_json"
SCRAPER_VERSION = "profile_scraper_v2"


# =========================================================
# Generic helpers
# =========================================================
def random_sleep(a: float = 1.0, b: float = 2.0) -> None:
    time.sleep(random.uniform(a, b))


def clean_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def get_text(node: Optional[Tag]) -> Optional[str]:
    if node is None:
        return None
    return clean_text(node.get_text(" ", strip=True))


def absolute_url(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    return urljoin(BASE_URL, href)


def extract_profile_parts_from_url(url_or_href: str) -> dict[str, Optional[str]]:
    last = url_or_href.rstrip("/").split("/")[-1]
    last = unquote(last)

    if "." in last:
        slug, profile_id = last.rsplit(".", 1)
    else:
        slug, profile_id = last, None

    return {"slug": slug, "profile_id": profile_id}


def safe_db_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json_dumps(value)
    return value


# =========================================================
# Selenium
# =========================================================
def fetch_html_selenium(url: str, headless: bool = True, wait_seconds: int = 25) -> str:
    options = Options()
    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1600,2400")
    options.add_argument("--lang=pl-PL")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)

    try:
        driver.get(url)

        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ln-profile-shell, ln-profile-details, h1"))
        )

        for y in [400, 1200, 2200, 3200, 4600]:
            driver.execute_script(f"window.scrollTo(0, {y});")
            time.sleep(0.5)

        time.sleep(1.5)
        return driver.page_source
    finally:
        driver.quit()


# =========================================================
# Parsing helpers
# =========================================================
def find_section_by_heading(soup: BeautifulSoup, heading: str) -> Optional[Tag]:
    for h4 in soup.select("h4.font-semibold"):
        if get_text(h4) == heading:
            return h4.find_parent("div", class_=re.compile(r"bg-color-background-default")) or h4.parent
    return None


def extract_source_text(container: Tag) -> list[str]:
    sources: list[str] = []
    for el in container.find_all(string=re.compile(r"Źródło danych")):
        parent = el.parent if isinstance(el.parent, Tag) else None
        if parent:
            txt = get_text(parent)
            if txt:
                sources.append(txt)
    return list(dict.fromkeys(sources))


# =========================================================
# Parse sections
# =========================================================
def parse_basic_identity(soup: BeautifulSoup, profile_url: str) -> dict[str, Any]:
    parts = extract_profile_parts_from_url(profile_url)

    h1 = soup.select_one("h1")
    orcid_link = soup.select_one("a[href*='orcid.org']")
    crumb = soup.select_one(".opi-breadcrumb-item-current")

    return {
        "profile_url": profile_url,
        "slug": parts["slug"],
        "profile_id": parts["profile_id"],
        "full_name": get_text(h1),
        "orcid": get_text(orcid_link),
        "orcid_url": orcid_link.get("href") if orcid_link else None,
        "breadcrumb_name": get_text(crumb),
    }


def parse_summary_block(soup: BeautifulSoup) -> dict[str, Any]:
    data = {
        "current_employment_summary": [],
        "discipline_summary": [],
        "specializations": [],
    }

    for div in soup.find_all("div", string=re.compile(r"^\s*Aktualne zatrudnienie\s*$")):
        parent = div.find_parent("div")
        if parent:
            ul = parent.find_next("ul")
            if ul:
                data["current_employment_summary"] = [
                    get_text(li) for li in ul.select("li") if get_text(li)
                ]
                break

    for div in soup.find_all("div", string=re.compile(r"^\s*Dyscyplina\s*$")):
        parent = div.find_parent("div")
        if parent:
            ul = parent.find_next("ul")
            if ul:
                data["discipline_summary"] = [
                    get_text(li) for li in ul.select("li") if get_text(li)
                ]
                break

    for span in soup.find_all("span", string=re.compile(r"^\s*Specjalności\s*$")):
        parent = span.find_parent("div")
        if parent:
            bold = parent.find_next("span", class_=re.compile(r"bold"))
            txt = get_text(bold)
            if txt:
                data["specializations"] = [clean_text(x) for x in txt.split(",") if clean_text(x)]
                break

    return data


def parse_tab_menu(soup: BeautifulSoup) -> list[dict[str, Any]]:
    return [
        {
            "label": get_text(a),
            "href": absolute_url(a.get("href")),
            "aria_disabled": a.get("aria-disabled"),
        }
        for a in soup.select("ln-profile-tab-menu a[href]")
    ]


def parse_employment_history(soup: BeautifulSoup) -> list[dict[str, Any]]:
    results = []
    section = find_section_by_heading(soup, "Zatrudnienie")
    if not section:
        return results

    for idx, row in enumerate(section.select("div.flex.flex-col.gap-4.lg\\:flex-row.py-5")):
        cols = row.find_all("div", recursive=False)
        if len(cols) < 2:
            continue

        period_block = cols[0]
        details_block = cols[1]

        period_texts = [get_text(x) for x in period_block.find_all("div", recursive=False) if get_text(x)]
        period = period_texts[0] if period_texts else get_text(period_block)
        duration = period_texts[1] if len(period_texts) > 1 else None

        institution_link = details_block.select_one("a.link-employment")

        results.append(
            {
                "row_order": idx,
                "period": period,
                "duration": duration,
                "institution": get_text(institution_link),
                "institution_url": institution_link.get("href") if institution_link else None,
                "source_json": extract_source_text(row),
            }
        )

    return results


def parse_degrees_and_titles(soup: BeautifulSoup) -> list[dict[str, Any]]:
    results = []
    section = find_section_by_heading(soup, "Stopnie i tytuły")
    if not section:
        return results

    for idx, row in enumerate(section.select("div.flex.flex-col.gap-4.lg\\:flex-row.py-5")):
        cols = row.find_all("div", recursive=False)
        if len(cols) < 2:
            continue

        year_block = cols[0]
        details_block = cols[1]

        title_el = details_block.select_one("span.font-semibold.text-body-large")
        p_tags = details_block.find_all("p")
        paragraph_texts = [get_text(p) for p in p_tags if get_text(p)]

        links = details_block.select("a[href]")
        linked_entities = [
            {"label": get_text(a), "href": a.get("href")}
            for a in links
            if get_text(a)
        ]

        results.append(
            {
                "row_order": idx,
                "year": get_text(year_block),
                "degree_or_title": get_text(title_el),
                "details_json": paragraph_texts,
                "linked_entities_json": linked_entities,
                "source_json": extract_source_text(row),
            }
        )

    return results


def parse_memberships(soup: BeautifulSoup) -> list[dict[str, Any]]:
    results = []
    section = find_section_by_heading(soup, "Członkostwa")
    if not section:
        return results

    for idx, row in enumerate(section.select("div.py-5.border-b")):
        role = get_text(row.select_one("span.font-semibold.text-body-large"))
        membership_link = row.select_one("a[href*='/gremiums/']")

        period = None
        for span in row.select("span"):
            txt = get_text(span)
            if txt and re.search(r"\d{4}\s*-\s*obecnie|\d{4}", txt):
                period = txt
                break

        org_text = None
        for div in row.select("div"):
            txt = get_text(div)
            if txt and "Politechnika Warszawska" in txt:
                org_text = txt
                break

        results.append(
            {
                "row_order": idx,
                "role": role,
                "membership_name": get_text(membership_link),
                "membership_url": absolute_url(membership_link.get("href")) if membership_link else None,
                "period": period,
                "organization_path": org_text,
                "source_json": extract_source_text(row),
            }
        )

    return results


def parse_publications(soup: BeautifulSoup) -> list[dict[str, Any]]:
    results = []
    section = find_section_by_heading(soup, "Publikacje")
    if not section:
        return results

    cards = section.select("div.rounded.shadow-card.flex.flex-col.gap-4")
    for idx, card in enumerate(cards):
        title_link = card.select_one("a[href*='/publications/']")
        title = get_text(title_link)
        title_url = absolute_url(title_link.get("href")) if title_link else None

        year_span = card.find("span", string=re.compile(r"^\d{4}$"))
        doi_link = card.select_one("a[href*='doi.org']")
        source_container = card.select_one("ln-publication-source")

        authors = None
        publication_type = None

        inline_groups = card.select("div.inline-flex.gap-2.items-center")
        for grp in inline_groups:
            txt = get_text(grp)
            if not txt:
                continue

            if ("Artykuł" in txt or "Książka" in txt):
                publication_type = txt
            elif title and txt != title and not re.fullmatch(r"\d{4}", txt):
                if "doi" not in txt.lower() and "Źródło danych" not in txt:
                    if authors is None and "," in txt:
                        authors = txt

        results.append(
            {
                "row_order": idx,
                "title": title,
                "title_url": title_url,
                "authors": authors,
                "publication_type": publication_type,
                "year": get_text(year_span),
                "doi": get_text(doi_link),
                "doi_url": doi_link.get("href") if doi_link else None,
                "source": get_text(source_container),
            }
        )

    return results


def parse_research_work_tabs(soup: BeautifulSoup) -> dict[str, list[dict[str, Any]]]:
    data = {"author": [], "promoter": [], "reviewer": []}
    section = find_section_by_heading(soup, "Postępowania awansowe")
    if not section:
        return data

    mapping = {
        "AUTHOR_pnl": "author",
        "PROMOTER_pnl": "promoter",
        "REVIEWER_pnl": "reviewer",
    }

    for panel_id, key in mapping.items():
        panel = section.select_one(f"div#{panel_id}")
        if not panel:
            continue

        for idx, card in enumerate(panel.select("div.rounded.shadow-card.flex.flex-col.gap-4")):
            title_link = card.select_one("a[href*='/research-work/']")

            description = None
            for div in card.select("div"):
                txt = get_text(div)
                if txt and ("Praca doktorska" in txt or "Praca habilitacyjna" in txt):
                    description = txt
                    break

            data[key].append(
                {
                    "row_order": idx,
                    "title": get_text(title_link),
                    "title_url": absolute_url(title_link.get("href")) if title_link else None,
                    "description": description,
                    "source": get_text(card.select_one("ln-source-array")),
                }
            )

    return data


def parse_external_profiles(soup: BeautifulSoup) -> list[dict[str, Any]]:
    results = []
    section = find_section_by_heading(soup, "Inne profile")
    if not section:
        return results

    for a in section.select("a[href]"):
        href = a.get("href")
        label = get_text(a)
        if href and label:
            results.append({"label": label, "url": href})

    return results


def parse_tag_cloud(soup: BeautifulSoup) -> list[str]:
    return [get_text(span) for span in soup.select("ln-tag-cloud .cloud-item") if get_text(span)]


def parse_coworkers(soup: BeautifulSoup) -> list[dict[str, Any]]:
    results = []

    header = soup.find("h4", string=re.compile(r"^\s*Współpracownicy\s*$"))
    if not header:
        return results

    container = header.find_parent("div")
    if not container:
        return results

    for slide in container.select("swiper-slide"):
        name_link = slide.select_one("a[href*='/ln/profiles/']")
        profile_url = absolute_url(name_link.get("href")) if name_link else None
        name = get_text(name_link)

        if not name:
            for sp in slide.select("span"):
                txt = get_text(sp)
                if txt and "publikacj" not in txt.lower():
                    name = txt
                    break

        shared_publications_info = None
        for sp in slide.select("span"):
            txt = get_text(sp)
            if txt and "publikacj" in txt.lower():
                shared_publications_info = txt
                break

        if name or shared_publications_info:
            results.append(
                {
                    "name": name,
                    "profile_url": profile_url,
                    "shared_publications_info": shared_publications_info,
                }
            )

    return results


def parse_all_profile_data(html: str, profile_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    data = {}
    data.update(parse_basic_identity(soup, profile_url))
    data.update(parse_summary_block(soup))

    data["tab_menu"] = parse_tab_menu(soup)
    data["employment_history"] = parse_employment_history(soup)
    data["degrees_and_titles"] = parse_degrees_and_titles(soup)
    data["memberships"] = parse_memberships(soup)
    data["publications_preview"] = parse_publications(soup)
    data["research_work"] = parse_research_work_tabs(soup)
    data["external_profiles"] = parse_external_profiles(soup)
    data["tag_cloud"] = parse_tag_cloud(soup)
    data["coworkers"] = parse_coworkers(soup)

    return data


# =========================================================
# DB helpers
# =========================================================
def scalar(conn, query: str, params: tuple = ()) -> int:
    cur = conn.execute(query, params)
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else 0


def get_global_profile_progress(conn) -> dict[str, int]:
    return {
        "total": scalar(conn, "SELECT COUNT(*) FROM profiles"),
        "discovered": scalar(conn, "SELECT COUNT(*) FROM profiles WHERE scrape_status = 'discovered'"),
        "running": scalar(conn, "SELECT COUNT(*) FROM profiles WHERE scrape_status = 'running'"),
        "scraped": scalar(conn, "SELECT COUNT(*) FROM profiles WHERE scrape_status = 'scraped'"),
        "failed": scalar(conn, "SELECT COUNT(*) FROM profiles WHERE scrape_status = 'failed'"),
        "employment_history": scalar(conn, "SELECT COUNT(*) FROM employment_history"),
        "degrees_titles": scalar(conn, "SELECT COUNT(*) FROM degrees_titles"),
        "memberships": scalar(conn, "SELECT COUNT(*) FROM memberships"),
        "publications": scalar(conn, "SELECT COUNT(*) FROM publications"),
        "research_work": scalar(conn, "SELECT COUNT(*) FROM research_work"),
    }


def print_global_profile_progress(conn) -> None:
    p = get_global_profile_progress(conn)
    processed = p["scraped"]
    pct = (processed / p["total"] * 100) if p["total"] else 0

    print("\n" + "=" * 90)
    print("GLOBAL PROFILE PROGRESS")
    print("=" * 90)
    print(
        f"Profiles: total={p['total']} | scraped={p['scraped']} | failed={p['failed']} | "
        f"discovered={p['discovered']} | running={p['running']}"
    )
    print(f"Processed: {processed}/{p['total']} ({pct:.2f}%)")
    print(
        f"Rows: employment={p['employment_history']} | degrees={p['degrees_titles']} | "
        f"memberships={p['memberships']} | publications={p['publications']} | research={p['research_work']}"
    )
    print("=" * 90 + "\n")


def get_next_profile_to_scrape(conn) -> dict[str, Any] | None:
    cur = conn.execute(
        """
        SELECT *
        FROM profiles
        WHERE scrape_status IN ('discovered', 'failed')
        ORDER BY id
        LIMIT 1
        """
    )
    row = cur.fetchone()
    return dict(row) if row else None


def mark_profile_running(conn, profile_id: str) -> None:
    conn.execute(
        """
        UPDATE profiles
        SET scrape_status = 'running'
        WHERE profile_id = ?
        """,
        (profile_id,),
    )
    conn.commit()


def mark_profile_done(
    conn,
    profile_id: str,
    full_name: str | None,
    breadcrumb_name: str | None,
    slug: str | None,
    profile_url: str,
    orcid: str | None,
    orcid_url: str | None,
    raw_html_path: str | None,
    raw_json_path: str | None,
) -> None:
    conn.execute(
        """
        UPDATE profiles
        SET slug = COALESCE(?, slug),
            profile_url = ?,
            full_name = COALESCE(?, full_name),
            breadcrumb_name = ?,
            orcid = ?,
            orcid_url = ?,
            raw_html_path = ?,
            raw_json_path = ?,
            last_scraped_at = CURRENT_TIMESTAMP,
            last_seen_at = CURRENT_TIMESTAMP,
            scrape_status = 'scraped',
            scrape_version = ?
        WHERE profile_id = ?
        """,
        (
            slug,
            profile_url,
            full_name,
            breadcrumb_name,
            orcid,
            orcid_url,
            raw_html_path,
            raw_json_path,
            SCRAPER_VERSION,
            profile_id,
        ),
    )
    conn.commit()


def mark_profile_failed(conn, profile_id: str) -> None:
    conn.execute(
        """
        UPDATE profiles
        SET scrape_status = 'failed'
        WHERE profile_id = ?
        """,
        (profile_id,),
    )
    conn.commit()


def start_scrape_run(conn, profile_id: str, profile_url: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO scrape_runs (
            profile_id,
            profile_url,
            status,
            scraper_version
        )
        VALUES (?, ?, 'started', ?)
        """,
        (profile_id, profile_url, SCRAPER_VERSION),
    )
    conn.commit()
    return cur.lastrowid


def finish_scrape_run_success(conn, run_id: int) -> None:
    conn.execute(
        """
        UPDATE scrape_runs
        SET status = 'success',
            finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (run_id,),
    )
    conn.commit()


def finish_scrape_run_failure(conn, run_id: int, error_message: str) -> None:
    conn.execute(
        """
        UPDATE scrape_runs
        SET status = 'failed',
            finished_at = CURRENT_TIMESTAMP,
            error_message = ?
        WHERE id = ?
        """,
        (error_message[:5000], run_id),
    )
    conn.commit()


def replace_profile_summary(conn, profile_id: str, data: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO profile_summary (
            profile_id,
            current_employment_summary_json,
            discipline_summary_json,
            specializations_json,
            tab_menu_json,
            external_profiles_json,
            tag_cloud_json,
            coworkers_json,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(profile_id) DO UPDATE SET
            current_employment_summary_json = excluded.current_employment_summary_json,
            discipline_summary_json = excluded.discipline_summary_json,
            specializations_json = excluded.specializations_json,
            tab_menu_json = excluded.tab_menu_json,
            external_profiles_json = excluded.external_profiles_json,
            tag_cloud_json = excluded.tag_cloud_json,
            coworkers_json = excluded.coworkers_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            profile_id,
            json_dumps(data.get("current_employment_summary")),
            json_dumps(data.get("discipline_summary")),
            json_dumps(data.get("specializations")),
            json_dumps(data.get("tab_menu")),
            json_dumps(data.get("external_profiles")),
            json_dumps(data.get("tag_cloud")),
            json_dumps(data.get("coworkers")),
        ),
    )


def replace_child_table(conn, table_name: str, profile_id: str, rows: list[dict[str, Any]], columns: list[str]) -> int:
    conn.execute(f"DELETE FROM {table_name} WHERE profile_id = ?", (profile_id,))

    if not rows:
        conn.commit()
        return 0

    placeholders = ", ".join(["?"] * (1 + len(columns)))
    columns_sql = ", ".join(["profile_id"] + columns)

    inserted = 0
    for row in rows:
        values = [profile_id]
        for col in columns:
            values.append(safe_db_value(row.get(col)))

        conn.execute(
            f"INSERT INTO {table_name} ({columns_sql}) VALUES ({placeholders})",
            values,
        )
        inserted += 1

    conn.commit()
    return inserted


def replace_research_work(conn, profile_id: str, research_work: dict[str, list[dict[str, Any]]]) -> int:
    conn.execute("DELETE FROM research_work WHERE profile_id = ?", (profile_id,))

    inserted = 0
    for category, rows in research_work.items():
        for row in rows:
            conn.execute(
                """
                INSERT INTO research_work (
                    profile_id,
                    category,
                    row_order,
                    title,
                    title_url,
                    description,
                    source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    category,
                    row.get("row_order"),
                    row.get("title"),
                    row.get("title_url"),
                    row.get("description"),
                    row.get("source"),
                ),
            )
            inserted += 1

    conn.commit()
    return inserted


def save_raw_files(profile_id: str, html: str, parsed_data: dict[str, Any]) -> tuple[str, str]:
    html_dir = ensure_dir(Path(__file__).parent / RAW_HTML_DIR)
    json_dir = ensure_dir(Path(__file__).parent / RAW_JSON_DIR)

    html_path = html_dir / f"{profile_id}.html"
    json_path = json_dir / f"{profile_id}.json"

    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(json.dumps(parsed_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return str(html_path), str(json_path)


# =========================================================
# Core processing
# =========================================================
def process_one_profile(conn, profile: dict[str, Any], headless: bool = True) -> None:
    profile_id = profile["profile_id"]
    profile_url = profile["profile_url"]
    old_name = profile.get("full_name")

    print("-" * 90)
    print(f"[START] profile_id     : {profile_id}")
    print(f"[START] old_name       : {old_name}")
    print(f"[START] url            : {profile_url}")
    print("-" * 90)

    mark_profile_running(conn, profile_id)
    run_id = start_scrape_run(conn, profile_id, profile_url)

    try:
        t0 = time.time()
        html = fetch_html_selenium(profile_url, headless=headless)
        fetch_seconds = time.time() - t0
        print(f"[FETCHED] HTML downloaded in {fetch_seconds:.2f}s")

        t1 = time.time()
        parsed = parse_all_profile_data(html, profile_url)
        parse_seconds = time.time() - t1
        print(f"[PARSED] profile parsed in {parse_seconds:.2f}s")

        print(
            f"[IDENTITY] full_name={parsed.get('full_name')} | "
            f"orcid={parsed.get('orcid')} | slug={parsed.get('slug')}"
        )

        print(
            f"[COUNTS] employment={len(parsed.get('employment_history', []))} | "
            f"degrees={len(parsed.get('degrees_and_titles', []))} | "
            f"memberships={len(parsed.get('memberships', []))} | "
            f"publications={len(parsed.get('publications_preview', []))} | "
            f"research(author={len(parsed.get('research_work', {}).get('author', []))}, "
            f"promoter={len(parsed.get('research_work', {}).get('promoter', []))}, "
            f"reviewer={len(parsed.get('research_work', {}).get('reviewer', []))})"
        )

        raw_html_path, raw_json_path = save_raw_files(profile_id, html, parsed)
        print(f"[FILES] raw_html={raw_html_path}")
        print(f"[FILES] raw_json={raw_json_path}")

        replace_profile_summary(conn, profile_id, parsed)

        employment_count = replace_child_table(
            conn,
            "employment_history",
            profile_id,
            parsed.get("employment_history", []),
            ["row_order", "period", "duration", "institution", "institution_url", "source_json"],
        )

        degrees_count = replace_child_table(
            conn,
            "degrees_titles",
            profile_id,
            parsed.get("degrees_and_titles", []),
            ["row_order", "year", "degree_or_title", "details_json", "linked_entities_json", "source_json"],
        )

        memberships_count = replace_child_table(
            conn,
            "memberships",
            profile_id,
            parsed.get("memberships", []),
            ["row_order", "role", "membership_name", "membership_url", "period", "organization_path", "source_json"],
        )

        publications_count = replace_child_table(
            conn,
            "publications",
            profile_id,
            parsed.get("publications_preview", []),
            ["row_order", "title", "title_url", "authors", "publication_type", "year", "doi", "doi_url", "source"],
        )

        research_count = replace_research_work(conn, profile_id, parsed.get("research_work", {}))

        print(
            f"[DB] employment={employment_count} | degrees={degrees_count} | "
            f"memberships={memberships_count} | publications={publications_count} | research={research_count}"
        )

        mark_profile_done(
            conn=conn,
            profile_id=profile_id,
            full_name=parsed.get("full_name"),
            breadcrumb_name=parsed.get("breadcrumb_name"),
            slug=parsed.get("slug"),
            profile_url=parsed.get("profile_url"),
            orcid=parsed.get("orcid"),
            orcid_url=parsed.get("orcid_url"),
            raw_html_path=raw_html_path,
            raw_json_path=raw_json_path,
        )

        finish_scrape_run_success(conn, run_id)
        print(f"[DONE] profile_id={profile_id} marked as scraped")

    except Exception as e:
        mark_profile_failed(conn, profile_id)
        finish_scrape_run_failure(conn, run_id, str(e))
        print(f"[FAILED] profile_id={profile_id} | error={e}")
        raise

    print("-" * 90)


# =========================================================
# Main
# =========================================================
def main(max_profiles_per_run: int | None = 10, headless: bool = True) -> None:
    conn = get_connection()

    processed = 0
    started_at = time.time()

    try:
        print_global_profile_progress(conn)

        while True:
            if max_profiles_per_run is not None and processed >= max_profiles_per_run:
                break

            profile = get_next_profile_to_scrape(conn)
            if not profile:
                print("No profile pending scrape.")
                break

            try:
                process_one_profile(conn, profile, headless=headless)
                processed += 1

                elapsed = time.time() - started_at
                avg = elapsed / processed if processed else 0

                print(
                    f"[RUN PROGRESS] processed_this_run={processed}"
                    + (f"/{max_profiles_per_run}" if max_profiles_per_run is not None else "")
                    + f" | elapsed={elapsed/60:.2f} min | avg_per_profile={avg:.2f}s"
                )

                print_global_profile_progress(conn)
                random_sleep(1.0, 2.0)

            except Exception:
                # error already logged in process_one_profile
                random_sleep(0.8, 1.4)

        total_elapsed = time.time() - started_at
        print("\n" + "#" * 90)
        print("RUN FINISHED")
        print("#" * 90)
        print(f"Processed profiles this run: {processed}")
        print(f"Elapsed time: {total_elapsed/60:.2f} minutes")
        if processed:
            print(f"Average per profile: {total_elapsed/processed:.2f} seconds")
        print("#" * 90)
        print_global_profile_progress(conn)

    except KeyboardInterrupt:
        print("\n" + "!" * 90)
        print("STOPPED BY USER (Ctrl+C)")
        print("You can safely restart later.")
        print("!" * 90)

    finally:
        conn.close()


if __name__ == "__main__":
    main(max_profiles_per_run=100000, headless=True )