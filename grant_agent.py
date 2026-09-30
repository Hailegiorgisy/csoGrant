import os
import json
import re
import datetime
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ================= Configuration =================
SEEN_DB_FILE = "seen_opportunities.json"

# Common browser User-Agent so RSS endpoints do not block the GitHub Action runner
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8"
}

# Thematic focus areas for Ease Africa
THEMATIC_KEYWORDS = [
    "health", "public health", "digital health", "technology", "tech",
    "data science", "artificial intelligence", "ai", "machine learning",
    "tb", "tuberculosis", "malaria", "hiv", "aids", "ntd", "neglected tropical",
    "ncd", "non-communicable", "mch", "maternal", "child health",
    "epidemiology", "informatics", "surveillance", "telemedicine", "community health"
]

# Geographic eligibility (includes broad regional and LMIC terms)
GEO_KEYWORDS = [
    "ethiopia", "east africa", "eastern africa", "africa", "sub-saharan",
    "lmic", "low- and middle-income", "developing countries", "global south",
    "all countries", "worldwide", "global"
]

OPPORTUNITY_TYPES = ["grant", "funding", "call for proposals", "conference", "seminar", "fellowship", "training", "award"]

# ================= State Persistence & Deduplication =================
def init_seen_db():
    if not os.path.exists(SEEN_DB_FILE):
        with open(SEEN_DB_FILE, "w", encoding="utf-8") as f:
            json.dump({"seen_ids": [], "updated_at": datetime.datetime.utcnow().isoformat()}, f, indent=2)

def load_seen_ids() -> set:
    init_seen_db()
    try:
        with open(SEEN_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("seen_ids", []))
    except Exception:
        return set()

def save_seen_id(opp_id: str):
    seen = load_seen_ids()
    seen.add(opp_id)
    with open(SEEN_DB_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_ids": list(seen), "updated_at": datetime.datetime.utcnow().isoformat()}, f, indent=2)

# ================= Multi-Source Opportunity Scrapers =================

def fetch_rss_feed(url: str, source_name: str) -> List[Dict[str, Any]]:
    """Generic XML parser for standard RSS and Atom feeds."""
    items = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=20)
        res.raise_for_status()
        root = ET.fromstring(res.content)

        # Standard RSS 2.0 channel/item
        channel = root.find("channel")
        elements = channel.findall("item") if channel is not None else root.findall(".//item")
        
        # If Atom feed (feed/entry)
        if not elements:
            elements = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for el in elements:
            title = el.findtext("title") or el.findtext("{http://www.w3.org/2005/Atom}title") or "Untitled"
            link = el.findtext("link") or el.findtext("{http://www.w3.org/2005/Atom}link") or ""
            desc = el.findtext("description") or el.findtext("{http://www.w3.org/2005/Atom}summary") or ""
            guid = el.findtext("guid") or el.findtext("{http://www.w3.org/2005/Atom}id") or link

            # Strip HTML tags from description snippet
            clean_desc = re.sub(r'<[^>]+>', ' ', desc).strip()[:2000]

            if link:
                items.append({
                    "id": guid.strip(),
                    "title": title.strip(),
                    "url": link.strip(),
                    "description": clean_desc,
                    "source": source_name
                })
        print(f"[{source_name}] Retrieved {len(items)} raw listings.")
    except Exception as e:
        print(f"[{source_name}] Ingestion error: {e}")
    return items

def fetch_grants_gov_opportunities() -> List[Dict[str, Any]]:
    """Queries Grants.gov Search2 open public API for global health grants."""
    items = []
    endpoint = "https://api.grants.gov/v1/api/search2"
    payload = {
        "fundingCategories": "HL", # Health category
        "oppStatuses": "posted",
        "keywords": "health Africa"
    }
    try:
        res = requests.post(endpoint, json=payload, headers=HEADERS, timeout=20)
        if res.status_code == 200:
            data = res.json()
            opp_list = data.get("oppHits", []) or data.get("opportunities", [])
            for opp in opp_list:
                opp_id = str(opp.get("id") or opp.get("opportunityNumber") or opp.get("number"))
                title = opp.get("title") or opp.get("opportunityTitle") or "Federal Grant Opportunity"
                link = f"https://www.grants.gov/search-results-detail/{opp_id}"
                desc = opp.get("synopsis") or opp.get("agencyName") or ""
                close_date = opp.get("closeDate") or ""
                items.append({
                    "id": f"grantsgov_{opp_id}",
                    "title": title,
                    "url": link,
                    "description": f"Agency: {opp.get('agencyName', '')}. Description: {desc}",
                    "source": "Grants.gov (Global Health / USAID / CDC)",
                    "raw_deadline": close_date
                })
            print(f"[Grants.gov] Retrieved {len(items)} opportunities.")
    except Exception as e:
        print(f"[Grants.gov] Query error: {e}")
    return items

def fetch_reliefweb_training() -> List[Dict[str, Any]]:
    """Queries ReliefWeb training API for health seminars and conferences."""
    items = []
    endpoint = "https://api.reliefweb.int/v1/training"
    payload = {
        "appname": "ease_africa_agent",
        "query": {"value": "health AND (Africa OR Ethiopia)"},
        "limit": 15,
        "fields": {"include": ["title", "body", "url", "source", "date"]}
    }
    try:
        res = requests.post(endpoint, json=payload, headers=HEADERS, timeout=20)
        if res.status_code == 200:
            for item in res.json().get("data", []):
                f = item.get("fields", {})
                items.append({
                    "id": f"rw_{item.get('id')}",
                    "title": f.get("title", ""),
                    "url": f.get("url", ""),
                    "description": f.get("body", "")[:2000],
                    "source": "ReliefWeb Training & Conferences"
                })
            print(f"[ReliefWeb Training] Retrieved {len(items)} training/seminar listings.")
    except Exception as e:
        print(f"[ReliefWeb Training] Query error: {e}")
    return items

# ================= Date Parsing & Filtering =================
def parse_deadline(text: str) -> Optional[datetime.datetime]:
    patterns = [
        r'(?:deadline|closing date|due date|apply before|submissions close)[:\s]+([A-Za-z]+ \d{1,2},? \d{4})',
        r'(?:deadline|closing date|due date)[:\s]+(\d{4}-\d{2}-\d{2})',
        r'(?:deadline|closing date)[:\s]+(\d{1,2}/\d{1,2}/\d{4})'
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1).replace(",", "")
            for fmt in ("%B %d %Y", "%b %d %Y", "%Y-%m-%d", "%m/%d/%Y"):
                try:
                    return datetime.datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
    return None

def filter_and_rank_opportunities(all_items: List[Dict[str, Any]], seen_ids: set) -> List[Dict[str, Any]]:
    qualified = []
    now = datetime.datetime.utcnow()

    for item in all_items:
        if item["id"] in seen_ids:
            continue

        text_content = f"{item['title']} {item['description']}".lower()

        # Check topic relevance
        has_topic = any(kw in text_content for kw in THEMATIC_KEYWORDS)
        if not has_topic:
            continue

        # Check geographic eligibility
        has_geo = any(geo in text_content for geo in GEO_KEYWORDS)
        # If source is FundsforNGOs or OpportunityDesk, geographic focus is already pre-filtered for development
        if not has_geo and "fundsforngos" not in item["source"].lower():
            continue

        # Evaluate deadline: must have at least 24-48 hours remaining
        deadline_dt = parse_deadline(text_content)
        if not deadline_dt and item.get("raw_deadline"):
            for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                try:
                    deadline_dt = datetime.datetime.strptime(item["raw_deadline"], fmt)
                    break
                except ValueError:
                    pass

        if deadline_dt:
            hours_left = (deadline_dt - now).total_seconds() / 3600
            if hours_left < 24:
                continue
            item["parsed_deadline"] = deadline_dt.strftime("%Y-%m-%d")
        else:
            item["parsed_deadline"] = "Rolling / Verify on website"

        # Categorize
        category = "Grant / Funding Opportunity"
        for t in OPPORTUNITY_TYPES:
            if t in text_content:
                category = t.title()
                break
        item["category"] = category

        qualified.append(item)

    return qualified

# ================= Application Letter & Proposal Generator =================
def generate_ease_africa_package(opp: Dict[str, Any]) -> Dict[str, str]:
    title = opp["title"]
    category = opp["category"]

    letter = (
        f"Subject: Expression of Interest / Application: {title}\n\n"
        f"Dear Selection Committee,\n\n"
        f"On behalf of Ease Africa, a civil society organization headquartered in Addis Ababa, Ethiopia, "
        f"we are pleased to submit our application for '{title}'.\n\n"
        f"About Ease Africa:\n"
        f"Ease Africa operates at the nexus of public health and modern technology. Our mission is to deploy "
        f"data-driven, community-centered solutions addressing high-burden conditions across Ethiopia and East Africa, "
        f"including Tuberculosis (TB), Malaria, HIV, Neglected Tropical Diseases (NTDs), Non-Communicable Diseases (NCDs), "
        f"and Maternal & Child Health (MCH).\n\n"
        f"Why Partner with an Emerging CSO:\n"
        f"While Ease Africa is an emerging organization, our team possesses established clinical, epidemiological, "
        f"and health informatics expertise. We offer grassroots agility, local cultural fluency, and direct community "
        f"engagement mechanisms that ensure accountable and transparent project delivery.\n\n"
        f"Alignment with This Call:\n"
        f"This {category.lower()} directly supports our strategic goal to improve healthcare access and primary health "
        f"data reporting in resource-constrained catchment areas.\n\n"
        f"Sincerely,\n"
        f"Programs & Research Team\n"
        f"Ease Africa | Addis Ababa, Ethiopia"
    )

    proposal = (
        f"# Project Concept Note: Strengthening Health Systems Through Digital Innovation\n"
        f"Organization: Ease Africa (Addis Ababa, Ethiopia)\n"
        f"Target Opportunity: {title}\n"
        f"Category: {category}\n\n"
        f"1. Executive Summary\n"
        f"Ease Africa proposes an initiative integrating community-level active case finding with lightweight "
        f"digital tracking tools to improve diagnosis, referral, and treatment adherence in target Ethiopian communities.\n\n"
        f"2. Problem Statement\n"
        f"Frontline primary healthcare facilities frequently face reporting lags, fragmented records, and limited "
        f"follow-up systems for priority diseases (TB, Malaria, MCH, NCDs), resulting in preventable morbidity.\n\n"
        f"3. Core Objectives\n"
        f"• Objective 1: Implement community-based screening protocols with woreda health offices.\n"
        f"• Objective 2: Utilize mobile/digital registries for real-time monitoring and patient tracing.\n"
        f"• Objective 3: Build frontline community health worker capacity via structured digital training modules.\n\n"
        f"4. Organizational Strengths (Emerging CSO Track)\n"
        f"• Deep community presence and grassroots stakeholder alignment.\n"
        f"• Interdisciplinary technical capacity spanning clinical medicine, data science, and public health.\n"
        f"• Lean, transparent project management and auditable milestones.\n\n"
        f"5. Sustainability Plan\n"
        f"Integration of reporting tools into regional health structures to maintain continuity beyond the grant lifecycle."
    )

    return {"letter": letter, "proposal": proposal}

# ================= Dispatch Handlers =================
def send_telegram_alert(bot_token: str, chat_id: str, opp: Dict[str, Any], package: Dict[str, str]):
    if not bot_token or not chat_id:
        return

    summary_msg = (
        f"🚨 *EASE AFRICA — Daily Opportunity Alert*\n\n"
        f"📌 *Title:* {opp['title']}\n"
        f"🏷 *Category:* {opp['category']}\n"
        f"🏢 *Source:* {opp['source']}\n"
        f"⏳ *Deadline:* {opp['parsed_deadline']}\n"
        f"🔗 [View Official Announcement]({opp['url']})\n\n"
        f"📄 *Application letter and concept proposal prepared below.*"
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": summary_msg, "parse_mode": "Markdown"}, timeout=15)
        
        doc_msg = (
            f"📝 *Ease Africa — Application Letter:*\n```\n{package['letter']}\n```\n\n"
            f"📑 *Concept Proposal Outline:*\n```\n{package['proposal']}\n```"
        )
        if len(doc_msg) > 4000:
            doc_msg = doc_msg[:3950] + "\n...[truncated for Telegram]"
        requests.post(url, json={"chat_id": chat_id, "text": doc_msg, "parse_mode": "Markdown"}, timeout=15)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")

def send_optional_email(smtp_user: str, smtp_pass: str, to_emails: List[str], opp: Dict[str, Any], package: Dict[str, str]):
    if not (smtp_user and smtp_pass and to_emails):
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Ease Africa Alert] {opp['category']}: {opp['title']}"
    msg["From"] = smtp_user
    msg["To"] = ", ".join(to_emails)

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.5; color: #222;">
        <h2 style="color: #0b5394;">Ease Africa — Daily Opportunity Match</h2>
        <p><strong>Opportunity:</strong> {opp['title']}</p>
        <p><strong>Category:</strong> {opp['category']}</p>
        <p><strong>Source:</strong> {opp['source']}</p>
        <p><strong>Deadline:</strong> {opp['parsed_deadline']}</p>
        <p><a href="{opp['url']}" style="background-color: #0b5394; color: white; padding: 8px 12px; text-decoration: none; border-radius: 4px;">Open Opportunity Page</a></p>
        <hr style="border: 0; border-top: 1px solid #ccc;"/>
        <h3>Draft Application Letter</h3>
        <pre style="background: #f7f9fa; padding: 12px; border: 1px solid #e1e4e8; border-radius: 4px; white-space: pre-wrap;">{package['letter']}</pre>
        <h3>Draft Concept Proposal</h3>
        <pre style="background: #f7f9fa; padding: 12px; border: 1px solid #e1e4e8; border-radius: 4px; white-space: pre-wrap;">{package['proposal']}</pre>
      </body>
    </html>
    """
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_emails, msg.as_string())
        print(f"Email successfully sent to {len(to_emails)} recipient(s).")
    except Exception as e:
        print(f"Error dispatching email: {e}")

# ================= Main Routine =================
def run():
    init_seen_db()

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.getenv("TELEGRAM_GROUP_CHAT_ID")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_APP_PASSWORD")

    raw_emails = os.getenv("RECIPIENT_EMAILS") or os.getenv("RECIPIENT_EMAIL", "")
    recipient_emails = [e.strip() for e in raw_emails.split(",") if e.strip()]

    seen_ids = load_seen_ids()

    # Aggregate across all 5 sources
    all_raw_items = []
    all_raw_items.extend(fetch_rss_feed("https://www.fundsforngos.org/feed/", "FundsforNGOs"))
    all_raw_items.extend(fetch_rss_feed("https://opportunitydesk.org/feed/", "Opportunity Desk"))
    all_raw_items.extend(fetch_rss_feed("https://philanthropynewsdigest.org/rfps/rss", "Philanthropy News Digest"))
    all_raw_items.extend(fetch_grants_gov_opportunities())
    all_raw_items.extend(fetch_reliefweb_training())

    print(f"Total raw opportunities ingested across sources: {len(all_raw_items)}")

    qualified = filter_and_rank_opportunities(all_raw_items, seen_ids)
    print(f"Found {len(qualified)} matching opportunities meeting Ease Africa criteria.")

    for opp in qualified:
        package = generate_ease_africa_package(opp)

        # Dispatch to Telegram Group
        send_telegram_alert(tg_token, tg_chat_id, opp, package)

        # Dispatch to email list if configured
        send_optional_email(smtp_user, smtp_pass, recipient_emails, opp, package)

        # Save ID to avoid repeating tomorrow
        save_seen_id(opp["id"])

if __name__ == "__main__":
    run()
