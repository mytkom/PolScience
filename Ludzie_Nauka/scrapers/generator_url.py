import json
import urllib.parse
from pathlib import Path

BASE_URL = "https://ludzie.nauka.gov.pl/ln/profiles;c="


def load_json(filename: str):
    file_path = Path(__file__).parent / filename

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        raise ValueError(f"{filename} is empty")

    return json.loads(content)


def build_url(
    institution: str,
    discipline: str | None = None,
    degree_code: str | None = None,
    page: int = 1,
) -> str:
    payload = {"f": {}}

    search_parts = [f"INSTITUTIONS:{institution}"]

    if discipline:
        search_parts.append(f"DISCIPLINE:{discipline}")

    payload["f"]["advancedSearch"] = "&&".join(search_parts)

    if degree_code:
        payload["f"]["degreeTitles"] = [{"code": degree_code}]

    # On this site, page 2 corresponds to pn=3 in the URL you observed.
    # So for page > 1, we encode pn = page + 1.
    if page > 1:
        payload["pn"] = page + 1

    encoded = urllib.parse.quote(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    )

    return BASE_URL + encoded


def generate_urls(
    institutions: list[str],
    disciplines: list[str],
    degree_codes: list[str] | None = None,
    max_pages: int = 100,
) -> list[dict]:
    urls = []

    if degree_codes:
        for inst in institutions:
            for degree in degree_codes:
                for disc in disciplines:
                    for page in range(1, max_pages + 1):
                        urls.append(
                            {
                                "institution": inst,
                                "discipline": disc,
                                "degree": degree,
                                "page": page,
                                "url": build_url(
                                    institution=inst,
                                    discipline=disc,
                                    degree_code=degree,
                                    page=page,
                                ),
                            }
                        )
    else:
        for inst in institutions:
            for disc in disciplines:
                for page in range(1, max_pages + 1):
                    urls.append(
                        {
                            "institution": inst,
                            "discipline": disc,
                            "degree": None,
                            "page": page,
                            "url": build_url(
                                institution=inst,
                                discipline=disc,
                                page=page,
                            ),
                        }
                    )

    return urls


if __name__ == "__main__":
    institutions = load_json("instytucje.json")
    disciplines = load_json("dyscypliny.json")

    # Take only the first ones for testing
    institutions = institutions[:1]
    disciplines = disciplines[:1]

    print(f"Testing with institutions: {institutions}")
    print(f"Testing with disciplines: {disciplines}")

    degree_codes = None

    urls = generate_urls(
        institutions=institutions,
        disciplines=disciplines,
        degree_codes=degree_codes,
        max_pages=5,  # also reduce pages for testing
    )

    output_path = Path(__file__).parent / "generated_urls_test.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(urls, f, ensure_ascii=False, indent=2)

    print(f"Generated {len(urls)} URLs")
    print(f"Saved to: {output_path}")

    print("\nURLs:")
    for item in urls:
        print(item["url"])