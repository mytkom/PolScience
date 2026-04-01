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


def random_sleep(a: float = 1.2, b: float = 2.4) -> None:
    time.sleep(random.uniform(a, b))


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
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.item-search-link[href*='/ln/profiles/']"))
        )

        random_sleep(2.0, 3.5)
        return driver.page_source
    finally:
        driver.quit()


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


def upsert_discovered_profile(conn, profile: dict[str, Any], source_search_page_id: int) -> None:
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


def main() -> None:
    conn = get_connection()

    try:
        page = get_next_pending_search_page(conn)
        if not page:
            print("No pending search_pages to scrape.")
            return

        page_id = page["id"]
        url = page["url"]

        print(f"Scraping search page id={page_id}")
        print(url)

        mark_search_page_running(conn, page_id)

        html = fetch_html_selenium(url, headless=False)
        profiles = parse_search_page(html)

        for profile in profiles:
            if not profile.get("profile_id"):
                continue
            upsert_discovered_profile(conn, profile, source_search_page_id=page_id)

        conn.commit()
        mark_search_page_done(conn, page_id, len(profiles))

        print(f"Found {len(profiles)} profiles on page {page_id}")

    except Exception as e:
        try:
            if "page_id" in locals():
                mark_search_page_failed(conn, page_id, str(e))
        finally:
            raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()