import json
import logging
import sqlite3
import time
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup
from db_config import get_db_connection, get_org_profile

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class GrantsGovAPI:
    """Queries official Grants.gov REST API (free public endpoint)."""

    BASE_URL = "https://api.grants.gov/v1/api/search2"

    def __init__(self):
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NGO-Grant-Finder/1.0",
        }

    def fetch_health_grants(
        self, keywords: List[str], max_results: int = 10
    ) -> List[Dict]:
        """Queries Grants.gov for posted grants matching keywords."""
        found_grants = []

        for keyword in keywords:
            payload = {
                "keyword": keyword,
                "oppStatuses": "posted",  # Only active/open grants
                "rows": max_results,
            }

            try:
                response = requests.post(
                    self.BASE_URL,
                    json=payload,
                    headers=self.headers,
                    timeout=15,
                )
                if response.status_code == 200:
                    data = response.json()
                    search_hits = (
                        data.get("searchResponse", {}).get("oppHits", []) or []
                    )

                    for hit in search_hits:
                        grant_id = hit.get("id")
                        title = hit.get("title", "Untitled Grant")
                        opp_number = hit.get("number", "")
                        source_url = f"https://www.grants.gov/search-results-detail/{grant_id}"

                        grant_data = {
                            "grant_title": f"[{opp_number}] {title}",
                            "source_url": source_url,
                            "deadline": hit.get(
                                "closeDate", "See link for deadline"
                            ),
                            "summary": (
                                f"Agency: {hit.get('agency', 'N/A')}. "
                                f"Doc Type: {hit.get('docType', 'Grant')}. "
                                f"CFDA: {hit.get('cfdaList', ['N/A'])[0] if hit.get('cfdaList') else 'N/A'}."
                            ),
                            "source": "Grants.gov API",
                        }
                        found_grants.append(grant_data)
                else:
                    logging.warning(
                        f"Grants.gov API returned status code {response.status_code} for keyword: {keyword}"
                    )
            except Exception as e:
                logging.error(
                    f"Error fetching from Grants.gov for keyword '{keyword}': {e}"
                )

            time.sleep(1)  # Respectful API delay

        return found_grants


class WebScraperEngine:
    """Scrapes structured health donor websites via BeautifulSoup."""

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HealthNGO-GrantBot/1.0"
        }

    def scrape_custom_donor_site(
        self, url: str, selector_rules: Dict
    ) -> List[Dict]:
        """Generic web scraper using CSS selectors.

        selector_rules example:
            {
                'container': 'div.grant-card',
                'title': 'h3.title',
                'link': 'a',
                'deadline': 'span.deadline',
                'summary': 'p.description'
            }
        """
        results = []
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            if res.status_code != 200:
                return results

            soup = BeautifulSoup(res.text, "html.parser")
            cards = soup.select(selector_rules["container"])

            for card in cards:
                title_el = card.select_one(selector_rules["title"])
                link_el = card.select_one(selector_rules["link"])
                deadline_el = (
                    card.select_one(selector_rules["deadline"])
                    if selector_rules.get("deadline")
                    else None
                )
                summary_el = (
                    card.select_one(selector_rules["summary"])
                    if selector_rules.get("summary")
                    else None
                )

                if title_el and link_el:
                    title = title_el.get_text(strip=True)
                    href = link_el.get("href", "")
                    if not href.startswith("http"):
                        # Convert relative URL to absolute
                        from urllib.parse import urljoin

                        href = urljoin(url, href)

                    results.append(
                        {
                            "grant_title": title,
                            "source_url": href,
                            "deadline": deadline_el.get_text(strip=True)
                            if deadline_el
                            else "Check Website",
                            "summary": summary_el.get_text(strip=True)
                            if summary_el
                            else "No summary provided.",
                            "source": "Web Scraper",
                        }
                    )
        except Exception as e:
            logging.error(f"Failed to scrape {url}: {e}")

        return results


def save_grants_to_db(grants: List[Dict]) -> int:
    """Deduplicates against source_url and stores new grants in SQLite."""
    new_records = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()

        for grant in grants:
            try:
                cursor.execute(
                    """
                    INSERT INTO grants (grant_title, source_url, deadline, summary, relevance_score, proposal_draft, notified)
                    VALUES (?, ?, ?, ?, NULL, NULL, 0)
                """,
                    (
                        grant["grant_title"],
                        grant["source_url"],
                        grant["deadline"],
                        grant["summary"],
                    ),
                )
                new_records += 1
            except sqlite3.IntegrityError:
                # Grant source_url already exists in DB -> skip
                continue

        conn.commit()

    logging.info(f"Saved {new_records} new grants into database.")
    return new_records


# --- Execution Pipeline ---
def run_grant_discovery():
    profile = get_org_profile()
    if not profile:
        logging.error("Organization profile is empty. Configure Phase 1 first.")
        return

    # Extract focus keywords from NGO profile
    keywords = profile.get("focus_areas", ["Health", "Maternal", "Infectious"])
    logging.info(
        f"Starting Grant Discovery Engine with keywords: {keywords}..."
    )

    all_discovered = []

    # 1. Grants.gov API Call
    api_engine = GrantsGovAPI()
    api_results = api_engine.fetch_health_grants(keywords=keywords)
    all_discovered.extend(api_results)

    # 2. Example Custom Web Scraper (Add target donor URLs)
    scraper_engine = WebScraperEngine()
    # Scraper call template (Uncomment when specifying target URLs):
    # custom_results = scraper_engine.scrape_custom_donor_site(
    #     url="https://example-health-donor.org/grants",
    #     selector_rules={
    #         'container': '.opportunity-item',
    #         'title': '.opp-title',
    #         'link': 'a.apply-link',
    #         'deadline': '.due-date',
    #         'summary': '.opp-abstract'
    #     }
    # )
    # all_discovered.extend(custom_results)

    # 3. Store new unique opportunities in DB
    new_count = save_grants_to_db(all_discovered)
    print(
        f"\n✅ Discovery Complete: Found {len(all_discovered)} potential opportunities. {new_count} new entries saved to DB."
    )


if __name__ == "__main__":
    run_grant_discovery()