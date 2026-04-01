from __future__ import annotations

import json
from pathlib import Path

from db_utils import get_connection

INPUT_JSON = "generated_urls.json"

def load_json(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list")

    return data


def insert_search_pages(items: list[dict]) -> int:
    conn = get_connection()
    inserted = 0

    try:
        cur = conn.cursor()

        for item in items:
            cur.execute(
                """
                INSERT OR IGNORE INTO search_pages (
                    institution,
                    discipline,
                    degree_code,
                    page_number,
                    url
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    item.get("institution"),
                    item.get("discipline"),
                    item.get("degree"),
                    item.get("page"),
                    item.get("url"),
                ),
            )
            if cur.rowcount > 0:
                inserted += 1

        conn.commit()
        return inserted
    finally:
        conn.close()


def main() -> None:
    base_dir = Path(__file__).parent
    input_path = base_dir / INPUT_JSON

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    items = load_json(input_path)
    inserted = insert_search_pages(items)

    print(f"Loaded {len(items)} search page rows from {input_path.name}")
    print(f"Inserted {inserted} new rows into search_pages")


if __name__ == "__main__":
    main()