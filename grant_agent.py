import os
import json
import re
import datetime
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict, Any, Optional

# ================= Configuration =================
SEEN_DB_FILE = "seen_opportunities.json"
RELIEFWEB_API_URL = "https://api.reliefweb.int/v1/reports"

# Core focus topics for Ease Africa
THEMATIC_KEYWORDS = [
    "health", "public health", "digital health", "technology", "tech",
    "data science", "artificial intelligence", "ai", "machine learning",
    "tb", "tuberculosis", "malaria", "hiv", "aids", "ntd",
    "neglected tropical", "ncd", "non-communicable", "mch",
    "maternal", "child health", "epidemiology", "informatics"
]

GEO_KEYWORDS = ["ethiopia", "east africa", "africa", "sub-saharan"]
OPPORTUNITY_TYPES = ["grant", "funding", "call for proposals", "conference", "seminar", "fellowship", "training"]

# ================= State Persistence & Deduplication =================
def init_seen_db():
    """Guarantees that seen_opportunities.json exists immediately upon startup."""
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

# ================= Scraping & Ingestion =================
def fetch_reliefweb_records() -> List[Dict[str, Any]]:
    """Ingests announcements, training calls, and reports from ReliefWeb API."""
    topics_query = " OR ".join(f'"{kw}"' for kw in THEMATIC_KEYWORDS[:8])
    geo_query = "Ethiopia OR Africa"
    
    payload = {
        "appname": "ease_africa_agent",
        "query": {
            "value": f"({topics_query}) AND ({geo_query})"
        },
        "filter": {
            "operator": "AND",
            "conditions": [
                {
                    "field": "format.name",
                    "value": ["Training", "Job", "Manual and Guideline", "Other"],
                    "operator": "OR"
                }
            ]
        },
        "limit": 20,
        "fields": {"include": ["title", "body", "url", "date", "source"]}
    }
    
    records = []
    try:
        res = requests.post(RELIEFWEB_API_URL, json=payload, timeout=20)
        res.raise_for_status()
        data = res.json()
        for item in data.get("data", []):
            f = item.get("fields", {})
            records.append({
                "id": str(item.get("id")),
                "title": f.get("title", "Untitled Opportunity"),
                "url": f.get("url", ""),
                "description": f.get("body", "")[:2500],
                "source": f.get("source", [{}])[0].get("name", "ReliefWeb / Global Partner"),
                "date_published": f.get("date", {}).get("created", "")
            })
    except Exception as e:
        print(f"Error querying ReliefWeb: {e}")
    return records

def parse_deadline(text: str) -> Optional[datetime.datetime]:
    patterns = [
        r'(?:deadline|closing date|due date|apply before|submissions close)[:\s]+([A-Za-z]+ \d{1,2},? \d{4})',
        r'(?:deadline|closing date|due date)[:\s]+(\d{4}-\d{2}-\d{2})'
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1).replace(",", "")
            for fmt in ("%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
                try:
                    return datetime.datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
    return None

def filter_opportunities(records: List[Dict[str, Any]], seen_ids: set) -> List[Dict[str, Any]]:
    qualified = []
    now = datetime.datetime.utcnow()

    for item in records:
        if item["id"] in seen_ids:
            continue

        text_content = f"{item['title']} {item['description']}".lower()

        has_topic = any(kw in text_content for kw in THEMATIC_KEYWORDS)
        has_geo = any(geo in text_content for geo in GEO_KEYWORDS)

        if not (has_topic and has_geo):
            continue

        deadline_dt = parse_deadline(text_content)
        if deadline_dt:
            hours_left = (deadline_dt - now).total_seconds() / 3600
            if hours_left < 24:
                # Skip if less than 24 hours remain
                continue
            item["parsed_deadline"] = deadline_dt.strftime("%Y-%m-%d")
        else:
            item["parsed_deadline"] = "Rolling / Not specified"

        detected_category = "Grant / Funding Call"
        for cat in OPPORTUNITY_TYPES:
            if cat in text_content:
                detected_category = cat.title()
                break
        item["category"] = detected_category

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
    records = fetch_reliefweb_records()
    qualified = filter_opportunities(records, seen_ids)

    print(f"Found {len(qualified)} new matching opportunities for Ease Africa.")

    for opp in qualified:
        package = generate_ease_africa_package(opp)
        
        # Dispatch to Telegram Group
        send_telegram_alert(tg_token, tg_chat_id, opp, package)
        
        # Dispatch to multiple email recipients
        send_optional_email(smtp_user, smtp_pass, recipient_emails, opp, package)
        
        # Save ID to prevent duplicates
        save_seen_id(opp["id"])

if __name__ == "__main__":
    run()
