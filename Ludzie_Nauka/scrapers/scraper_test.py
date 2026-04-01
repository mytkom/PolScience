from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
import time


BASE_URL = "https://ludzie.nauka.gov.pl"


def fetch_html_selenium(url: str) -> str:
    options = Options()
    # comment out the next line if you want to see the browser
    # options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1400,1200")

    driver = webdriver.Chrome(options=options)

    try:
        driver.get(url)

        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.item-search-link[href*='/ln/profiles/']"))
        )

        time.sleep(3)
        return driver.page_source

    finally:
        driver.quit()


def extract_profile_parts(href: str):
    last = href.rstrip("/").split("/")[-1]

    if "." in last:
        name_slug, profile_id = last.rsplit(".", 1)
    else:
        name_slug, profile_id = last, None

    return name_slug, profile_id


def parse_search_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    links = soup.select("a.item-search-link[href*='/ln/profiles/']")
    print(f"DEBUG: found {len(links)} profile links")

    seen = set()

    for a in links:
        href = a.get("href")
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)
        _, profile_id = extract_profile_parts(href)

        if full_url in seen:
            continue
        seen.add(full_url)

        card = a
        title = card.select_one("h2.item-search-title")
        institution = card.select_one(".item-search-employment")
        disciplines = card.select(".discipline")

        name_slug, profile_id = extract_profile_parts(href)

        results.append({
            "profile_url": full_url,
            "profile_id": profile_id,
            "name_slug": unquote(name_slug),
            "display_name": title.get_text(" ", strip=True) if title else None,
            "institution": institution.get_text(" ", strip=True) if institution else None,
            "disciplines": [d.get_text(" ", strip=True) for d in disciplines if d.get_text(" ", strip=True)]
        })

    return results


if __name__ == "__main__":
    url = "https://ludzie.nauka.gov.pl/ln/profiles;c=%7B%22f%22:%7B%22advancedSearch%22:%22INSTITUTIONS:Politechnika%20Warszawska&&DISCIPLINE:matematyka%22%7D%7D"

    html = fetch_html_selenium(url)
    profiles = parse_search_page(html)

    print(f"\nFound {len(profiles)} profiles\n")

    for p in profiles[:10]:
        print(p)