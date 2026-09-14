import json
import logging
import sqlite3
import time
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from db_config import get_db_connection, get_org_profile

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class MultiSourceGrantEngine:

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HealthGrantBot/2.0"
        }

    # --- SOURCE 1: Grants.gov API ---
    def fetch_grants_gov(self, keywords: list) -> list:
        url = "https://api.grants.gov/v1/api/search2"
        results = []
        for kw in keywords:
            try:
                res = requests.post(
                    url,
                    json={"keyword": kw, "oppStatuses": "posted", "rows": 10},
                    headers=self.headers,
                    timeout=15,
                )
                if res.status_code == 200:
                    for hit in res.json().get("searchResponse", {}).get(
                        "oppHits", []
                    ):
                        results.append(
                            {
                                "grant_title": f"[{hit.get('number', '')}] {hit.get('title')}",
                                "source_url": f"https://www.grants.gov/search-results-detail/{hit.get('id')}",
                                "deadline": hit.get(
                                    "closeDate", "Check website"
                                ),
                                "summary": f"Agency: {hit.get('agency', 'N/A')}. CFDA: {hit.get('cfdaList', ['N/A'])[0] if hit.get('cfdaList') else 'N/A'}",
                                "source": "Grants.gov API",
                            }
                        )
            except Exception as e:
                logging.error(f"Grants.gov error for {kw}: {e}")
        return results

    # --- SOURCE 2: FundsForNGOs (Health & Africa Filter) ---
    def fetch_funds_for_ngos(self) -> list:
        url = "https://www2.fundsforngos.org/category/health/"
        results = [] 
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                articles = soup.select("article")
                for art in articles[:15]:
                    title_el = art.select_one("h2.entry-title a")
                    excerpt_el = art.select_one("div.entry-summary") or art.select_one("div.entry-content")
                    
                    if title_el:
                        title = title_el.get_text(strip=True)
                        link = title_el.get("href")
                        summary = excerpt_el.get_text(strip=True) if excerpt_el else "Civil society grant opportunity."
                        
                        results.append({
                            "grant_title": title,
                            "source_url": link,
                            "deadline": "See article link",
                            "summary": summary[:300] + "...",
                            "source": "FundsForNGOs"
                        })
        except Exception as e:
            logging.error(f"FundsForNGOs scraper error: {e}")
        return results

    # --- SOURCE 3: Grand Challenges in Global Health ---
    def fetch_grand_challenges(self) -> list:
        url = "https://grandchallenges.org/grants"
        results = []
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                cards = soup.select(".view-content .views-row") or soup.select(".grant-opportunity")
                
                for card in cards:
                    title_el = card.select_one("a")
                    desc_el = card.select_one("p")
                    if title_el:
                        results.append({
                            "grant_title": title_el.get_text(strip=True),
                            "source_url": urljoin(url, title_el.get("href", "")),
                            "deadline": "Check posting",
                            "summary": desc_el.get_text(strip=True) if desc_el else "Global Health innovation grant.",
                            "source": "Grand Challenges"
                        })
        except Exception as e:
            logging.error(f"Grand Challenges scraper error: {e}")
        return results

    # --- SOURCE 4: Generic CSS Selector Scraper for Custom Donor Pages ---
    def scrape_custom_site(self, url: str, source_name: str, selectors: dict) -> list:
        results = []
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                for item in soup.select(selectors["container"]):
                    t_el = item.select_one(selectors["title"])
                    l_el = item.select_one(selectors["link"])
                    d_el = item.select_one(selectors["deadline"]) if selectors.get("deadline") else None
                    
                    if t_el and l_el:
                        results.append({
                            "grant_title": t_el.get_text(strip=True),
                            "source_url": urljoin(url, l_el.get("href", "")),
                            "deadline": d_el.get_text(strip=True) if d_el else "Check website",
                            "summary": f"Scraped from {source_name}",
                            "source": source_name
                        })
        except Exception as e:
            logging.error(f"Failed custom scrape for {source_name}: {e}")
        return results


def run_aggregated_discovery():
    profile = get_org_profile()
    keywords = profile.get("focus_areas", ["Health", "Maternal", "Infectious"])
    
    engine = MultiSourceGrantEngine()
    all_discovered = []

    logging.info("--> Querying Grants.gov API...")
    all_discovered.extend(engine.fetch_grants_gov(keywords))

    logging.info("--> Scraping FundsForNGOs...")
    all_discovered.extend(engine.fetch_funds_for_ngos())

    logging.info("--> Scraping Grand Challenges Global Health...")
    all_discovered.extend(engine.fetch_grand_challenges())

    # Save to Database with Deduplication
    new_saved = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for g in all_discovered:
            try:
                cursor.execute("""
                    INSERT INTO grants (grant_title, source_url, deadline, summary, relevance_score, proposal_draft, notified)
                    VALUES (?, ?, ?, ?, NULL, NULL, 0)
                """, (g["grant_title"], g["source_url"], g["deadline"], f"[{g['source']}] {g['summary']}"))
                new_saved += 1
            except sqlite3.IntegrityError:
                continue # Skip if source_url already exists
        conn.commit()

    print(f"\n✅ Aggregation Complete: Discovered {len(all_discovered)} potential opportunities from multiple platforms. Saved {new_saved} new entries.")

if __name__ == "__main__":
    run_aggregated_discovery()