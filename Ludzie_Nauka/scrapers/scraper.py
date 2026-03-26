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
    options.add_argument("--headless=new")  # remove if you want to see browser
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1400,1200")

    driver = webdriver.Chrome(options=options)

    try:
        driver.get(url)

        # Wait until at least one result item appears
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li.list-item.list-item-profile"))
        )

        time.sleep(2)  # extra safety for Angular rendering
        html = driver.page_source
        return html

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

    items = soup.select("li.list-item.list-item-profile")
    print(f"DEBUG: found {len(items)} matching result blocks in HTML")

    for item in items:
        a = item.select_one("a.item-search-link")
        if not a:
            continue

        href = a.get("href")
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)
        name_slug, profile_id = extract_profile_parts(href)

        title = item.select_one("h2.item-search-title")
        institution = item.select_one("span.item-search-employment")
        disciplines = item.select("li.discipline")

        results.append({
            "profile_url": full_url,
            "profile_id": profile_id,
            "name_slug": unquote(name_slug),
            "display_name": title.get_text(" ", strip=True) if title else None,
            "institution": institution.get_text(" ", strip=True) if institution else None,
            "disciplines": [d.get_text(" ", strip=True) for d in disciplines]
        })

    return results


if __name__ == "__main__":
    url = "https://ludzie.nauka.gov.pl/ln/profiles;c=%7B%22f%22%3A%7B%22advancedSearch%22%3A%22INSTITUTIONS%3APolitechnika%20Warszawska%26%26DISCIPLINE%3Amatematyka%22%7D%7D"

    html = fetch_html_selenium(url)
    profiles = parse_search_page(html)

    print(f"\nFound {len(profiles)} profiles\n")

    for p in profiles[:5]:
        print(p)