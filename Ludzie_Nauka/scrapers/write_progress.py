from __future__ import annotations

from pathlib import Path

from db_utils import get_connection


OUTPUT_FILE = "progress_scraping.txt"


def scalar(conn, query: str) -> int:
    cur = conn.execute(query)
    row = cur.fetchone()
    return int(row[0] or 0)


def main() -> None:
    conn = get_connection()

    try:
        total_search_pages = scalar(conn, "SELECT COUNT(*) FROM search_pages")
        done_search_pages = scalar(conn, "SELECT COUNT(*) FROM search_pages WHERE status = 'done'")
        failed_search_pages = scalar(conn, "SELECT COUNT(*) FROM search_pages WHERE status = 'failed'")
        pending_search_pages = scalar(conn, "SELECT COUNT(*) FROM search_pages WHERE status IN ('pending', 'running')")

        total_profiles = scalar(conn, "SELECT COUNT(*) FROM profiles")
        scraped_profiles = scalar(conn, "SELECT COUNT(*) FROM profiles WHERE scrape_status = 'scraped'")
        failed_profiles = scalar(conn, "SELECT COUNT(*) FROM profiles WHERE scrape_status = 'failed'")
        pending_profiles = scalar(conn, "SELECT COUNT(*) FROM profiles WHERE scrape_status IN ('discovered', 'running')")

        content = f"""Last update: generated from SQLite

SEARCH PAGES
------------
Total: {total_search_pages}
Done: {done_search_pages}
Failed: {failed_search_pages}
Pending/Running: {pending_search_pages}

PROFILES
--------
Total discovered: {total_profiles}
Scraped successfully: {scraped_profiles}
Failed: {failed_profiles}
Pending/Running: {pending_profiles}
"""

        output_path = Path(__file__).parent / OUTPUT_FILE
        output_path.write_text(content, encoding="utf-8")

        print(content)
        print(f"Saved progress file to: {output_path}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()