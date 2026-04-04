from __future__ import annotations

import random
import re
import time
from typing import Any
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db_utils import get_connection


BASE_URL = "https://ludzie.nauka.gov.pl"
SCRAPER_VERSION = "search_scraper_v3"


# =========================
# Helpers
# =========================

def random_sleep(a: float = 1.0, b: float = 2.0) -> None:
    time.sleep(random.uniform(a, b))


def clean_text(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def extract_profile_parts(href: str) -> tuple[str | None, str | None]:
    last = href.rstrip("/").split("/")[-1]
    last = unquote(last)

    if "." in last:
        slug, profile_id = last.rsplit(".", 1)
        return slug, profile_id

    return last, None


# =========================
# Selenium
# =========================

def fetch_html_selenium(url: str, headless: bool = True, wait_seconds: int = 25) -> str:
    options = Options()
    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1400,1600")
    options.add_argument("--lang=pl-PL")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)

    try:
        driver.get(url)

        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        random_sleep(2.0, 3.0)
        return driver.page_source
    finally:
        driver.quit()


# =========================
# Parsing
# =========================

def parse_search_page(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, Any]] = []

    links = soup.select("a.item-search-link[href*='/ln/profiles/']")
    seen: set[str] = set()

    for a in links:
        href = a.get("href")
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        seen.add(full_url)

        slug, profile_id = extract_profile_parts(href)

        title = a.select_one("h2.item-search-title")
        institution = a.select_one(".item-search-employment")
        disciplines = a.select(".discipline")

        results.append(
            {
                "profile_url": full_url,
                "profile_id": profile_id,
                "slug": slug,
                "full_name": clean_text(title.get_text(" ", strip=True) if title else None),
                "institution": clean_text(institution.get_text(" ", strip=True) if institution else None),
                "disciplines": [
                    clean_text(d.get_text(" ", strip=True))
                    for d in disciplines
                    if clean_text(d.get_text(" ", strip=True))
                ],
            }
        )

    return results


# =========================
# DB Progress helpers
# =========================

def scalar(conn, query: str, params: tuple = ()) -> int:
    cur = conn.execute(query, params)
    row = cur.fetchone()
    return row[0] if row and row[0] is not None else 0


def get_global_progress(conn) -> dict[str, int]:
    return {
        "total": scalar(conn, "SELECT COUNT(*) FROM search_pages"),
        "pending": scalar(conn, "SELECT COUNT(*) FROM search_pages WHERE status = 'pending'"),
        "running": scalar(conn, "SELECT COUNT(*) FROM search_pages WHERE status = 'running'"),
        "done": scalar(conn, "SELECT COUNT(*) FROM search_pages WHERE status = 'done'"),
        "failed": scalar(conn, "SELECT COUNT(*) FROM search_pages WHERE status = 'failed'"),
        "skipped": scalar(conn, "SELECT COUNT(*) FROM search_pages WHERE status = 'skipped'"),
        "profiles_total": scalar(conn, "SELECT COUNT(*) FROM profiles"),
    }


def print_global_progress(conn) -> None:
    p = get_global_progress(conn)
    processed = p["done"] + p["skipped"]
    pct = (processed / p["total"] * 100) if p["total"] else 0

    print("\n" + "=" * 90)
    print("GLOBAL PROGRESS")
    print("=" * 90)
    print(
        f"Search pages: total={p['total']} | done={p['done']} | skipped={p['skipped']} | "
        f"failed={p['failed']} | pending={p['pending']} | running={p['running']}"
    )
    print(f"Processed: {processed}/{p['total']} ({pct:.2f}%)")
    print(f"Profiles discovered so far: {p['profiles_total']}")
    print("=" * 90 + "\n")


# =========================
# DB search_pages
# =========================

def get_next_pending_search_page(conn) -> dict[str, Any] | None:
    cur = conn.execute(
        """
        SELECT *
        FROM search_pages
        WHERE status IN ('pending', 'failed')
        ORDER BY id
        LIMIT 1
        """
    )
    row = cur.fetchone()
    return dict(row) if row else None


def mark_search_page_running(conn, page_id: int) -> None:
    conn.execute(
        """
        UPDATE search_pages
        SET status = 'running',
            updated_at = CURRENT_TIMESTAMP,
            last_error = NULL
        WHERE id = ?
        """,
        (page_id,),
    )
    conn.commit()


def mark_search_page_done(conn, page_id: int, profiles_found: int) -> None:
    conn.execute(
        """
        UPDATE search_pages
        SET status = 'done',
            profiles_found = ?,
            updated_at = CURRENT_TIMESTAMP,
            last_error = NULL
        WHERE id = ?
        """,
        (profiles_found, page_id),
    )
    conn.commit()


def mark_search_page_failed(conn, page_id: int, error_message: str) -> None:
    conn.execute(
        """
        UPDATE search_pages
        SET status = 'failed',
            updated_at = CURRENT_TIMESTAMP,
            last_error = ?
        WHERE id = ?
        """,
        (error_message[:5000], page_id),
    )
    conn.commit()


def skip_later_pages_for_combination(
    conn,
    institution: str | None,
    discipline: str | None,
    degree_code: str | None,
    current_page_number: int,
) -> int:
    cur = conn.execute(
        """
        UPDATE search_pages
        SET status = 'skipped',
            updated_at = CURRENT_TIMESTAMP,
            last_error = 'Skipped because an earlier page for the same combination had zero results'
        WHERE institution = ?
          AND COALESCE(discipline, '') = COALESCE(?, '')
          AND COALESCE(degree_code, '') = COALESCE(?, '')
          AND page_number > ?
          AND status IN ('pending', 'failed')
        """,
        (institution, discipline, degree_code, current_page_number),
    )
    conn.commit()
    return cur.rowcount


# =========================
# DB profiles
# =========================

def profile_exists(conn, profile_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM profiles WHERE profile_id = ? LIMIT 1",
        (profile_id,),
    )
    return cur.fetchone() is not None


def upsert_discovered_profile(conn, profile: dict[str, Any], source_search_page_id: int) -> str:
    existed_before = profile_exists(conn, profile["profile_id"])

    conn.execute(
        """
        INSERT INTO profiles (
            profile_id,
            slug,
            profile_url,
            full_name,
            first_seen_at,
            last_seen_at,
            scrape_status,
            source_search_page_id
        )
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'discovered', ?)
        ON CONFLICT(profile_id) DO UPDATE SET
            slug = COALESCE(excluded.slug, profiles.slug),
            profile_url = excluded.profile_url,
            full_name = COALESCE(excluded.full_name, profiles.full_name),
            last_seen_at = CURRENT_TIMESTAMP
        """,
        (
            profile["profile_id"],
            profile["slug"],
            profile["profile_url"],
            profile["full_name"],
            source_search_page_id,
        ),
    )

    return "updated" if existed_before else "inserted"


# =========================
# Core processing
# =========================

def process_one_search_page(conn, page: dict[str, Any], headless: bool = True) -> None:
    page_id = page["id"]
    url = page["url"]
    institution = page["institution"]
    discipline = page["discipline"]
    degree_code = page["degree_code"]
    page_number = page["page_number"]

    print("-" * 90)
    print(f"[START] search_page_id={page_id}")
    print(f"page_number      : {page_number}")
    print(f"institution      : {institution}")
    print(f"discipline       : {discipline}")
    print(f"degree_code      : {degree_code}")
    print(f"url              : {url}")
    print("-" * 90)

    mark_search_page_running(conn, page_id)

    t0 = time.time()
    html = fetch_html_selenium(url, headless=headless)
    scrape_seconds = time.time() - t0

    print(f"[FETCHED] HTML downloaded in {scrape_seconds:.2f}s")

    profiles = parse_search_page(html)
    valid_profiles = [p for p in profiles if p.get("profile_id")]

    print(f"[PARSE] Raw profile cards found   : {len(profiles)}")
    print(f"[PARSE] Valid profiles with ID    : {len(valid_profiles)}")

    inserted_count = 0
    updated_count = 0

    for idx, profile in enumerate(valid_profiles, start=1):
        action = upsert_discovered_profile(conn, profile, source_search_page_id=page_id)

        if action == "inserted":
            inserted_count += 1
        else:
            updated_count += 1

        print(
            f"    [{idx}/{len(valid_profiles)}] {action.upper():8} "
            f"profile_id={profile['profile_id']} | {profile.get('full_name')}"
        )

    conn.commit()
    mark_search_page_done(conn, page_id, len(valid_profiles))

    print(f"[DB] inserted={inserted_count} | updated={updated_count}")
    print(f"[DONE] search_page_id={page_id} marked as done")

    if len(valid_profiles) == 0:
        skipped_count = skip_later_pages_for_combination(
            conn=conn,
            institution=institution,
            discipline=discipline,
            degree_code=degree_code,
            current_page_number=page_number,
        )
        print(
            f"[SKIP-CHAIN] Empty page detected on page {page_number}. "
            f"Skipped {skipped_count} later pages for same combination."
        )

    print("-" * 90)


# =========================
# Main
# =========================

def main(max_pages_per_run: int = 20, headless: bool = False) -> None:
    conn = get_connection()

    processed = 0
    started_at = time.time()

    try:
        print_global_progress(conn)

        while processed < max_pages_per_run:
            page = get_next_pending_search_page(conn)
            if not page:
                print("No pending search_pages left.")
                break

            try:
                process_one_search_page(conn, page, headless=headless)
                processed += 1

                elapsed = time.time() - started_at
                avg = elapsed / processed if processed else 0

                print(
                    f"[RUN PROGRESS] processed_this_run={processed}/{max_pages_per_run} | "
                    f"elapsed={elapsed/60:.2f} min | avg_per_page={avg:.2f}s"
                )

                print_global_progress(conn)

                random_sleep(1.0, 2.0)

            except Exception as e:
                mark_search_page_failed(conn, page["id"], str(e))
                print(f"[FAILED] search_page_id={page['id']} | error={e}")

        total_elapsed = time.time() - started_at
        print("\n" + "#" * 90)
        print("RUN FINISHED")
        print("#" * 90)
        print(f"Processed search pages this run: {processed}")
        print(f"Elapsed time: {total_elapsed/60:.2f} minutes")
        if processed:
            print(f"Average per page: {total_elapsed/processed:.2f} seconds")
        print("#" * 90)
        print_global_progress(conn)

    except KeyboardInterrupt:
        print("\n" + "!" * 90)
        print("STOPPED BY USER (Ctrl+C)")
        print("You can safely restart later.")
        print("!" * 90)

    finally:
        conn.close()


if __name__ == "__main__":
    main()