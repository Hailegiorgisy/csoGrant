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

# Opportunity categories
OPPORTUNITY_TYPES = ["grant", "funding", "call for proposals", "conference", "seminar", "fellowship", "training"]

# ================= State Persistence & Deduplication =================
def load_seen_ids() -> set:
    if os.path.exists(SEEN_DB_FILE):
        try:
            with open(SEEN_DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("seen_ids", []))
        except Exception:
            return set()
    return set()

def save_seen_id(opp_id: str):
    seen = load_seen_ids()
    seen.add(opp_id)
    with open(SEEN_DB_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_ids": list(seen), "updated_at": datetime.datetime.utcnow().isoformat()}, f, indent=2)

# ================= Scraping & Opportunity Ingestion =================
def fetch_reliefweb_records() -> List[Dict[str, Any]]:
    """Ingests calls, reports, training sessions, and announcements from ReliefWeb."""
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
    """Attempts to identify dates near deadline keywords."""
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
    """Enforces thematic match, geography, deadline threshold, and deduplication."""
    qualified = []
    now = datetime.datetime.utcnow()

    for item in records:
        if item["id"] in seen_ids:
            continue

        text_content = f"{item['title']} {item['description']}".lower()

        # Check topic match (at least one key topic)
        has_topic = any(kw in text_content for kw in THEMATIC_KEYWORDS)
        # Check geographic alignment
        has_geo = any(geo in text_content for geo in GEO_KEYWORDS)

        if not (has_topic and has_geo):
            continue

        # Deadline evaluation: ensure window has at least 24-48 hours
        deadline_dt = parse_deadline(text_content)
        if deadline_dt:
            hours_left = (deadline_dt - now).total_seconds() / 3600
            if hours_left < 24:
                # Omit expired or immediately closing opportunities (< 24h)
                continue
            item["parsed_deadline"] = deadline_dt.strftime("%Y-%m-%d")
        else:
            item["parsed_deadline"] = "Rolling / Not specified (Verify on site)"

        # Detect opportunity category
        detected_category = "Grant / Funding Call"
        for cat in OPPORTUNITY_TYPES:
            if cat in text_content:
                detected_category = cat.title()
                break
        item["category"] = detected_category

        qualified.append(item)

    return qualified

# ================= Proposal & Application Letter Generator =================
def generate_ease_africa_package(opp: Dict[str, Any]) -> Dict[str, str]:
    """
    Constructs an application letter and a targeted concept proposal tailored
    specifically for Ease Africa as an emerging local CSO.
    """
    title = opp["title"]
    category = opp["category"]

    letter = (
        f"Subject: Expression of Interest / Application: {title}\n\n"
        f"Dear Selection Committee,\n\n"
        f"On behalf of Ease Africa, a civil society organization headquartered in Addis Ababa, Ethiopia, "
        f"we are pleased to submit our application for the '{title}'.\n\n"
        f"Who We Are:\n"
        f"Ease Africa operates at the intersection of public health and modern technology. Our core mandate "
        f"is to deploy data-driven, community-anchored interventions that address high-burden health challenges—"
        f"including Tuberculosis (TB), Malaria, HIV, Neglected Tropical Diseases (NTDs), Non-Communicable Diseases (NCDs), "
        f"and Maternal & Child Health (MCH).\n\n"
        f"Why Partner with an Emerging CSO:\n"
        f"While Ease Africa is an agile and emerging organization, our team combines robust clinical acumen, "
        f"epidemiological research background, and full-stack health informatics capability. Being community-based, "
        f"we offer deep local access, cultural fluency, and rapid on-the-ground operational deployment across Ethiopia "
        f"and regional hubs.\n\n"
        f"Alignment with This Opportunity:\n"
        f"This {category.lower()} represents an essential strategic fit with our vision to bridge healthcare delivery "
        f"gaps using digital health tools and targeted community surveillance.\n\n"
        f"We welcome the opportunity to discuss our implementation plan in further detail.\n\n"
        f"Warm regards,\n"
        f"Executive Leadership & Programs Team\n"
        f"Ease Africa | Addis Ababa, Ethiopia"
    )

    proposal = (
        f"# Project Concept Note: Digital Health & Community Health Systems Strengthening\n"
        f"Organization: Ease Africa (Addis Ababa, Ethiopia)\n"
        f"Target Opportunity: {title}\n"
        f"Category: {category}\n\n"
        f"1. Executive Summary\n"
        f"Ease Africa proposes a collaborative, high-impact initiative designed to enhance local primary healthcare "
        f"and epidemiological surveillance in target catchment areas. Leveraging lightweight digital health workflows "
        f"and community health worker training, this project bridges facility-level care with community outreach.\n\n"
        f"2. Problem Statement\n"
        f"In underserved communities across Ethiopia and East Africa, timely case identification, referral tracking, "
        f"and retention in care for priority conditions (TB, Malaria, MCH, and chronic NCDs) remain constrained by "
        f"paper-based data silos and limited digital infrastructure.\n\n"
        f"3. Proposed Project Objectives\n"
        f"• Objective 1: Deploy community-level screening and active case-finding tools in collaboration with local health bureaus.\n"
        f"• Objective 2: Establish data pipeline integration for real-time tracking, risk stratification, and patient follow-up.\n"
        f"• Objective 3: Strengthen frontline health worker capacity through structured digital training modules.\n\n"
        f"4. Organizational Capacity & Risk Mitigation (Emerging CSO Track)\n"
        f"• Agility: Direct, unbureaucratic community access and established grassroots trust.\n"
        f"• Technical Bench: In-house technical leadership across public health, clinical medicine, and software development.\n"
        f"• Accountability: Transparent financial controls, milestones tracking, and alignment with regional health guidelines.\n\n"
        f"5. Expected Outcomes & Sustainability\n"
        f"• Improved screening throughput and reduced diagnostic delays.\n"
        f"• Transition of workflows to woreda health offices for institutional longevity."
    )

    return {"letter": letter, "proposal": proposal}

# ================= Dispatch Handlers =================
def send_telegram_alert(bot_token: str, chat_id: str, opp: Dict[str, Any], package: Dict[str, str]):
    """Sends a summary notification to the Telegram Group, split into chunks if needed."""
    if not bot_token or not chat_id:
        return

    # Message 1: Opportunity Alert Overview
    summary_msg = (
        f"🚨 *EASE AFRICA — Daily Opportunity Alert*\n\n"
        f"📌 *Title:* {opp['title']}\n"
        f"🏷 *Type:* {opp['category']}\n"
        f"🏢 *Source:* {opp['source']}\n"
        f"⏳ *Deadline:* {opp['parsed_deadline']}\n"
        f"🔗 [View Official Announcement]({opp['url']})\n\n"
        f"📄 *Application letter and concept proposal have been generated below.*"
    )
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": summary_msg, "parse_mode": "Markdown"}, timeout=15)

    # Message 2: Draft Application Letter & Proposal (Truncated to fit Telegram's 4096 char limit)
    doc_msg = (
        f"📝 *Ease Africa — Application Letter:*\n```\n{package['letter']}\n```\n\n"
        f"📑 *Concept Proposal Outline:*\n```\n{package['proposal']}\n```"
    )
    if len(doc_msg) > 4000:
        doc_msg = doc_msg[:3950] + "\n...[truncated for Telegram]"
    
    requests.post(url, json={"chat_id": chat_id, "text": doc_msg, "parse_mode": "Markdown"}, timeout=15)

def send_optional_email(smtp_user: str, smtp_pass: str, to_email: str, opp: Dict[str, Any], package: Dict[str, str]):
    """Sends full HTML email if SMTP credentials are provided in secrets."""
    if not (smtp_user and smtp_pass and to_email):
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Ease Africa Alert] {opp['category']}: {opp['title']}"
    msg["From"] = smtp_user
    msg["To"] = to_email

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
            server.sendmail(smtp_user, [to_email], msg.as_string())
    except Exception as e:
        print(f"Error dispatching email: {e}")

# ================= Main Routine =================
def run():
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.getenv("TELEGRAM_GROUP_CHAT_ID")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_APP_PASSWORD")
    recipient_email = os.getenv("RECIPIENT_EMAIL")

    seen_ids = load_seen_ids()
    records = fetch_reliefweb_records()
    qualified = filter_opportunities(records, seen_ids)

    print(f"Found {len(qualified)} new matching opportunities for Ease Africa.")

    for opp in qualified:
        package = generate_ease_africa_package(opp)
        
        # Send to Telegram Group
        send_telegram_alert(tg_token, tg_chat_id, opp, package)
        
        # Optional Email dispatch
        send_optional_email(smtp_user, smtp_pass, recipient_email, opp, package)
        
        # Persist ID to prevent repeating tomorrow
        save_seen_id(opp["id"])

if __name__ == "__main__":
    run()