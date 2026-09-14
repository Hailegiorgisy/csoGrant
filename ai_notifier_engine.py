import html
import json
import logging
import os
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import urllib.parse
import urllib.request
from google import genai
from google.genai import types

from db_config import get_db_connection, get_org_profile, get_active_members

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- CONFIGURATION (Populated via Environment Variables / Secrets) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")       # Your Gmail address
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "") # Your Gmail App Password
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Initialize Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


# =====================================================================
# PART 1: GEMINI AI RELEVANCE EVALUATION & PROPOSAL GENERATOR
# =====================================================================

def evaluate_and_draft_proposal(grant: dict, profile: dict) -> tuple[int, str]:
    """
    Evaluates grant relevance against NGO profile using Gemini 1.5 Flash.
    Returns: (relevance_score [0-100], proposal_markdown_draft)
    """
    if not client:
        logging.warning("GEMINI_API_KEY not configured. Skipping AI evaluation.")
        return 50, "AI Proposal Drafting skipped: Missing API key."

    prompt = f"""
You are an expert NGO Grant Specialist and Writer for local civil society health organizations.

### NGO PROFILE:
- Name: {profile.get('org_name')}
- Legal Status: {profile.get('legal_status')}
- Region/Scope: {profile.get('geographic_scope')}
- Annual Budget: {profile.get('budget_scale')}
- Core Focus Areas: {json.dumps(profile.get('focus_areas'))}
- Target Populations: {json.dumps(profile.get('target_populations'))}
- Historical Achievements: {profile.get('past_achievements')}

### GRANT OPPORTUNITY TO EVALUATE:
- Title: {grant.get('grant_title')}
- Summary/Requirements: {grant.get('summary')}
- Deadline: {grant.get('deadline')}
- Link: {grant.get('source_url')}

### YOUR TASK:
1. Determine a **Relevance Score (0 to 100)** evaluating how well this grant matches our NGO's scope, focus, and legal eligibility.
2. If Relevance Score is 60 or higher, write a concise, professional **Draft Concept Note / Proposal Outline** tailored specifically to this grant call and our NGO achievements. Include:
   - Project Title & Executive Summary
   - Problem Statement & Local Alignment
   - Objectives & Proposed Interventions
   - Expected Impact & Monitoring Strategy
   - High-Level Budget Allocation Concept

Respond strictly in JSON format as follows:
{{
  "relevance_score": INTEGER_BETWEEN_0_AND_100,
  "reasoning": "Brief explanation of eligibility and alignment",
  "proposal_draft": "Markdown-formatted proposal concept note"
}}
"""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        res_data = json.loads(response.text)
        score = int(res_data.get("relevance_score", 0))
        draft = res_data.get("proposal_draft", "No proposal generated.")
        logging.info(f"Evaluated '{grant['grant_title']}': Score = {score}/100")
        return score, draft
    except Exception as e:
        logging.error(f"Error calling Gemini API: {e}")
        return 0, "Error during AI evaluation."


# =====================================================================
# PART 2: TELEGRAM NOTIFICATION DISPATCHER
# =====================================================================

def send_telegram_alert(chat_id: str, grant: dict, score: int, proposal_draft: str) -> bool:
    """Sends structured grant alert to Telegram chat/channel using Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return False

    message = (
        f"🚨 <b>NEW HEALTH GRANT ALERT</b> (Fit Score: {score}%)\n\n"
        f"📌 <b>Title:</b> {html.escape(grant['grant_title'])}\n"
        f"⏳ <b>Deadline:</b> {html.escape(grant['deadline'])}\n"
        f"📝 <b>Summary:</b> {html.escape(grant['summary'][:250])}...\n\n"
        f"🔗 <a href='{grant['source_url']}'>View Grant Application</a>\n\n"
        f"📄 <i>AI Proposal Draft has been generated and emailed to the team.</i>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }).encode('utf-8')

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except Exception as e:
        logging.error(f"Failed to send Telegram alert to {chat_id}: {e}")
        return False


# =====================================================================
# PART 3: EMAIL BROADCAST DISPATCHER
# =====================================================================

def send_email_alert(recipient_email: str, recipient_name: str, grant: dict, score: int, proposal_draft: str) -> bool:
    """Sends styled HTML email notification with grant details and proposal draft."""
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        logging.warning("SMTP credentials not set. Skipping email dispatch.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🎯 [Grant Opportunity {score}% Match] {grant['grant_title']}"
    msg["From"] = f"Grant Alert Engine <{SMTP_EMAIL}>"
    msg["To"] = recipient_email

    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
      <div style="max-width: 650px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px;">
        <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">
          Health Grant Opportunity Identified
        </h2>
        <p>Hello <b>{recipient_name}</b>,</p>
        <p>Our automated grant finder detected a new grant matching our organizational focus profile:</p>

        <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
          <tr style="background-color: #f8f9fa;">
            <td style="padding: 10px; font-weight: bold; width: 30%;">Grant Title:</td>
            <td style="padding: 10px;">{grant['grant_title']}</td>
          </tr>
          <tr>
            <td style="padding: 10px; font-weight: bold;">Match Relevance:</td>
            <td style="padding: 10px;"><b style="color: #27ae60;">{score}% Match</b></td>
          </tr>
          <tr style="background-color: #f8f9fa;">
            <td style="padding: 10px; font-weight: bold;">Application Deadline:</td>
            <td style="padding: 10px; color: #c0392b;"><b>{grant['deadline']}</b></td>
          </tr>
          <tr>
            <td style="padding: 10px; font-weight: bold;">Summary & Scope:</td>
            <td style="padding: 10px;">{grant['summary']}</td>
          </tr>
          <tr style="background-color: #f8f9fa;">
            <td style="padding: 10px; font-weight: bold;">Application Link:</td>
            <td style="padding: 10px;"><a href="{grant['source_url']}" style="color: #3498db;">Apply / Details Here</a></td>
          </tr>
        </table>

        <div style="background-color: #f4f6f7; padding: 15px; border-left: 4px solid #3498db; margin-top: 20px;">
          <h3 style="margin-top: 0; color: #2c3e50;">Auto-Generated Proposal Concept Draft</h3>
          <pre style="white-space: pre-wrap; font-family: inherit; font-size: 14px;">{proposal_draft}</pre>
        </div>

        <p style="font-size: 12px; color: #7f8c8d; margin-top: 30px; text-align: center;">
          Sent by Automated NGO Grant Scraper & Engine • Powered by Free Tier Infrastructure
        </p>
      </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, recipient_email, msg.as_string())
        logging.info(f"Email alert sent to {recipient_email}")
        return True
    except Exception as e:
        logging.error(f"Failed to send email to {recipient_email}: {e}")
        return False


# =====================================================================
# PART 4: PIPELINE ORCHESTRATOR
# =====================================================================

def process_unnotified_grants():
    """Main job: Evaluates new grants in DB, drafts proposals, and alerts members."""
    profile = get_org_profile()
    if not profile:
        logging.error("No NGO profile found in database.")
        return

    members = get_active_members()
    if not members:
        logging.warning("No active members found for notifications.")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Fetch up to 5 unnotified grants per batch
        cursor.execute("SELECT * FROM grants WHERE notified = 0 LIMIT 5;")
        unprocessed = [dict(row) for row in cursor.fetchall()]

    if not unprocessed:
        logging.info("No new unnotified grants in database.")
        return

    logging.info(f"Processing {len(unprocessed)} new grant records...")

    for grant in unprocessed:
        # Step 1: AI Evaluation & Proposal Generation
        score, proposal_draft = evaluate_and_draft_proposal(grant, profile)

        # Step 2: Dispatch Notifications to Team Members if score >= 50
        if score >= 50:
            for member in members:
                # Email Dispatch
                if member.get("email"):
                    send_email_alert(member["email"], member["full_name"], grant, score, proposal_draft)

                # Telegram Dispatch
                if member.get("telegram_chat_id"):
                    send_telegram_alert(member["telegram_chat_id"], grant, score, proposal_draft)

        # Step 3: Update Database Record
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE grants 
                SET relevance_score = ?, proposal_draft = ?, notified = 1 
                WHERE id = ?;
            """, (score, proposal_draft, grant["id"]))
            conn.commit()

    print("✅ Grant evaluation and notification pipeline execution finished.")


if __name__ == "__main__":
    process_unnotified_grants()