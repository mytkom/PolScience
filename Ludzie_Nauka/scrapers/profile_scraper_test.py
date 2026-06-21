from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup, Tag
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


BASE_URL = "https://ludzie.nauka.gov.pl"


# =========================
# Selenium fetch
# =========================
def fetch_html_selenium(url: str, headless: bool = True, wait_seconds: int = 25) -> str:
    options = Options()
    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1600,2200")
    options.add_argument("--lang=pl-PL")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)

    try:
        driver.get(url)

        # Wait for a strong element from the profile page
        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ln-profile-shell, ln-profile-details, h1"))
        )

        # Small extra delay for lazy-rendered sections
        time.sleep(4)

        # Scroll gradually so some lazy content gets mounted
        for y in [500, 1200, 2200, 3200, 4500]:
            driver.execute_script(f"window.scrollTo(0, {y});")
            time.sleep(0.7)

        time.sleep(2)
        return driver.page_source

    finally:
        driver.quit()


# =========================
# Helpers
# =========================
def clean_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def get_text(node: Optional[Tag]) -> Optional[str]:
    if node is None:
        return None
    return clean_text(node.get_text(" ", strip=True))


def extract_profile_parts_from_url(url_or_href: str) -> Dict[str, Optional[str]]:
    """
    Example:
    /ln/profiles/krzysztof.che%C5%82mi%C5%84ski.mPCgc6OyQIM
    => slug: krzysztof.chełmiński
       profile_id: mPCgc6OyQIM
    """
    last = url_or_href.rstrip("/").split("/")[-1]
    last = unquote(last)

    if "." in last:
        slug, profile_id = last.rsplit(".", 1)
    else:
        slug, profile_id = last, None

    return {
        "slug": slug,
        "profile_id": profile_id,
    }


def absolute_url(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    return urljoin(BASE_URL, href)


def find_section_by_heading(soup: BeautifulSoup, heading: str) -> Optional[Tag]:
    for h4 in soup.select("h4.font-semibold"):
        if get_text(h4) == heading:
            return h4.find_parent("div", class_=re.compile(r"bg-color-background-default")) or h4.parent
    return None


def extract_source_text(container: Tag) -> List[str]:
    sources = []
    for el in container.find_all(string=re.compile(r"Źródło danych")):
        parent = el.parent if isinstance(el.parent, Tag) else None
        if parent:
            txt = get_text(parent)
            if txt:
                sources.append(txt)
    return list(dict.fromkeys(sources))


# =========================
# Core parsing
# =========================
def parse_basic_identity(soup: BeautifulSoup, profile_url: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "profile_url": profile_url,
        "slug": None,
        "profile_id": None,
        "full_name": None,
        "orcid": None,
        "orcid_url": None,
        "breadcrumb_name": None,
    }

    parts = extract_profile_parts_from_url(profile_url)
    data["slug"] = parts["slug"]
    data["profile_id"] = parts["profile_id"]

    h1 = soup.select_one("h1")
    data["full_name"] = get_text(h1)

    orcid_link = soup.select_one("a[href*='orcid.org']")
    if orcid_link:
        data["orcid"] = get_text(orcid_link)
        data["orcid_url"] = orcid_link.get("href")

    crumb = soup.select_one(".opi-breadcrumb-item-current")
    data["breadcrumb_name"] = get_text(crumb)

    return data


def parse_summary_block(soup: BeautifulSoup) -> Dict[str, Any]:
    """
    Reads the top summary area:
    - Aktualne zatrudnienie
    - Dyscyplina
    - Specjalności
    """
    data: Dict[str, Any] = {
        "current_employment_summary": [],
        "discipline_summary": [],
        "specializations": [],
    }

    # Current employment summary
    for div in soup.find_all("div", string=re.compile(r"^\s*Aktualne zatrudnienie\s*$")):
        parent = div.find_parent("div")
        if parent:
            ul = parent.find_next("ul")
            if ul:
                items = [get_text(li) for li in ul.select("li") if get_text(li)]
                data["current_employment_summary"] = items
                break

    # Discipline summary
    for div in soup.find_all("div", string=re.compile(r"^\s*Dyscyplina\s*$")):
        parent = div.find_parent("div")
        if parent:
            ul = parent.find_next("ul")
            if ul:
                items = [get_text(li) for li in ul.select("li") if get_text(li)]
                data["discipline_summary"] = items
                break

    # Specializations
    for span in soup.find_all("span", string=re.compile(r"^\s*Specjalności\s*$")):
        parent = span.find_parent("div")
        if parent:
            bold = parent.find_next("span", class_=re.compile(r"bold"))
            txt = get_text(bold)
            if txt:
                specs = [clean_text(x) for x in txt.split(",") if clean_text(x)]
                data["specializations"] = specs
                break

    return data


def parse_tab_menu(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    tabs = []
    for a in soup.select("ln-profile-tab-menu a[href]"):
        tabs.append({
            "label": get_text(a),
            "href": absolute_url(a.get("href")),
            "aria_disabled": a.get("aria-disabled"),
        })
    return tabs


def parse_employment_history(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    section = find_section_by_heading(soup, "Zatrudnienie")
    if not section:
        return results

    for row in section.select("div.flex.flex-col.gap-4.lg\\:flex-row.py-5"):
        cols = row.find_all("div", recursive=False)
        if len(cols) < 2:
            continue

        period_block = cols[0]
        details_block = cols[1]

        period_texts = [get_text(x) for x in period_block.find_all("div", recursive=False) if get_text(x)]
        main_period = period_texts[0] if period_texts else get_text(period_block)
        duration = period_texts[1] if len(period_texts) > 1 else None

        institution_link = details_block.select_one("a.link-employment")
        institution_name = None
        institution_url = None
        if institution_link:
            institution_name = get_text(institution_link)
            institution_url = institution_link.get("href")

        source_texts = extract_source_text(row)

        results.append({
            "period": main_period,
            "duration": duration,
            "institution": institution_name,
            "institution_url": institution_url,
            "source": source_texts,
        })

    return results


def parse_degrees_and_titles(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    section = find_section_by_heading(soup, "Stopnie i tytuły")
    if not section:
        return results

    for row in section.select("div.flex.flex-col.gap-4.lg\\:flex-row.py-5"):
        cols = row.find_all("div", recursive=False)
        if len(cols) < 2:
            continue

        year_block = cols[0]
        details_block = cols[1]

        year = get_text(year_block)

        title_el = details_block.select_one("span.font-semibold.text-body-large")
        degree_name = get_text(title_el)

        p_tags = details_block.find_all("p")
        paragraph_texts = [get_text(p) for p in p_tags if get_text(p)]

        links = details_block.select("a[href]")
        linked_entities = [{
            "label": get_text(a),
            "href": a.get("href"),
        } for a in links if get_text(a)]

        results.append({
            "year": year,
            "degree_or_title": degree_name,
            "details": paragraph_texts,
            "linked_entities": linked_entities,
            "source": extract_source_text(row),
        })

    return results


def parse_memberships(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    section = find_section_by_heading(soup, "Członkostwa")
    if not section:
        return results

    for row in section.select("div.py-5.border-b"):
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

        results.append({
            "role": role,
            "membership_name": get_text(membership_link),
            "membership_url": absolute_url(membership_link.get("href")) if membership_link else None,
            "period": period,
            "organization_path": org_text,
            "source": extract_source_text(row),
        })

    return results


def parse_publications(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    section = find_section_by_heading(soup, "Publikacje")
    if not section:
        return results

    cards = section.select("div.rounded.shadow-card.flex.flex-col.gap-4")
    for card in cards:
        title_link = card.select_one("a[href*='/publications/']")
        title = get_text(title_link)
        title_url = absolute_url(title_link.get("href")) if title_link else None

        authors = None
        year = None
        doi = None
        doi_url = None
        publication_type = None
        source = None

        # Authors
        for div in card.select("div"):
            txt = get_text(div)
            if txt and ("Chełmiński" in txt or "," in txt):
                if "Artykuł" not in txt and "Książka" not in txt and not re.fullmatch(r"\d{4}", txt):
                    authors = txt
                    break

        # Type / venue
        for div in card.select("div"):
            txt = get_text(div)
            if txt and ("Artykuł" in txt or "Książka" in txt):
                publication_type = txt
                break

        # Year
        year_span = card.find("span", string=re.compile(r"^\d{4}$"))
        year = get_text(year_span)

        # DOI
        doi_link = card.select_one("a[href*='doi.org']")
        if doi_link:
            doi = get_text(doi_link)
            doi_url = doi_link.get("href")

        # Source
        source_container = card.select_one("ln-publication-source")
        if source_container:
            source = get_text(source_container)

        results.append({
            "title": title,
            "title_url": title_url,
            "authors": authors,
            "publication_type": publication_type,
            "year": year,
            "doi": doi,
            "doi_url": doi_url,
            "source": source,
        })

    return results


def parse_research_work_tabs(soup: BeautifulSoup) -> Dict[str, List[Dict[str, Any]]]:
    """
    Postępowania awansowe:
    - Autor
    - Promotor
    - Recenzent

    Important:
    In the static page_source, hidden tab panels may still be present in DOM.
    """
    data = {
        "author": [],
        "promoter": [],
        "reviewer": [],
    }

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

        for card in panel.select("div.rounded.shadow-card.flex.flex-col.gap-4"):
            title_link = card.select_one("a[href*='/research-work/']")
            title = get_text(title_link)
            title_url = absolute_url(title_link.get("href")) if title_link else None

            description = None
            source = None

            for div in card.select("div"):
                txt = get_text(div)
                if txt and ("Praca doktorska" in txt or "Praca habilitacyjna" in txt):
                    description = txt
                    break

            source = get_text(card.select_one("ln-source-array"))

            data[key].append({
                "title": title,
                "title_url": title_url,
                "description": description,
                "source": source,
            })

    return data


def parse_external_profiles(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    results = []

    section = find_section_by_heading(soup, "Inne profile")
    if not section:
        return results

    for a in section.select("a[href]"):
        href = a.get("href")
        label = get_text(a)
        if href and label:
            results.append({
                "label": label,
                "url": href,
            })

    return results


def parse_tag_cloud(soup: BeautifulSoup) -> List[str]:
    return [get_text(span) for span in soup.select("ln-tag-cloud .cloud-item") if get_text(span)]


def parse_coworkers(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    results = []

    section_header = soup.find("h4", string=re.compile(r"^\s*Współpracownicy\s*$"))
    if not section_header:
        return results

    container = section_header.find_parent("div")
    if not container:
        return results

    for slide in container.select("swiper-slide"):
        name_link = slide.select_one("a[href*='/ln/profiles/']")
        plain_spans = slide.select("span")
        count_text = None
        name = None
        profile_url = None

        if name_link:
            name = get_text(name_link)
            profile_url = absolute_url(name_link.get("href"))

        if not name:
            for sp in plain_spans:
                txt = get_text(sp)
                if txt and "publikacj" not in txt.lower():
                    name = txt
                    break

        for sp in plain_spans:
            txt = get_text(sp)
            if txt and "publikacj" in txt.lower():
                count_text = txt
                break

        if name or count_text:
            results.append({
                "name": name,
                "profile_url": profile_url,
                "shared_publications_info": count_text,
            })

    return results


def parse_all_profile_data(html: str, profile_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    data: Dict[str, Any] = {}
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


# =========================
# Entry point
# =========================
if __name__ == "__main__":
    profile_url = "https://ludzie.nauka.gov.pl/ln/profiles/krzysztof.che%C5%82mi%C5%84ski.mPCgc6OyQIM"

    html = fetch_html_selenium(profile_url, headless=False)
    profile_data = parse_all_profile_data(html, profile_url)

    print(json.dumps(profile_data, ensure_ascii=False, indent=2))

    with open("krzysztof_chelminski_profile.json", "w", encoding="utf-8") as f:
        json.dump(profile_data, f, ensure_ascii=False, indent=2)

    print("\nSaved to krzysztof_chelminski_profile.json")