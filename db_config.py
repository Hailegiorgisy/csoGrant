import json
import sqlite3
from typing import Dict, List, Optional

DB_NAME = "organization.db"


def get_db_connection() -> sqlite3.Connection:
    """Establishes a connection to SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # Enables dict-like column access
    return conn


def init_db():
    """Initializes SQLite database tables."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Organization Profile
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS organization_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                org_name TEXT NOT NULL,
                legal_status TEXT NOT NULL,
                geographic_scope TEXT NOT NULL,
                budget_scale TEXT NOT NULL,
                focus_areas TEXT NOT NULL,
                target_populations TEXT NOT NULL,
                past_achievements TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        )

        # Member Contacts
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                telegram_chat_id TEXT UNIQUE,
                role TEXT DEFAULT 'Member',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        )

        # Grants & Proposals storage
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS grants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grant_title TEXT NOT NULL,
                source_url TEXT UNIQUE NOT NULL,
                deadline TEXT,
                summary TEXT,
                relevance_score INTEGER,
                proposal_draft TEXT,
                notified INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        )

        conn.commit()
    print("✅ Database initialized successfully.")


def upsert_org_profile(
    org_name: str,
    legal_status: str,
    geographic_scope: str,
    budget_scale: str,
    focus_areas: List[str],
    target_populations: List[str],
    past_achievements: str,
):
    """Inserts or updates the single NGO profile record."""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Check if record exists
        cursor.execute("SELECT id FROM organization_profile LIMIT 1;")
        existing = cursor.fetchone()

        focus_json = json.dumps(focus_areas)
        target_json = json.dumps(target_populations)

        if existing:
            cursor.execute(
                """
                UPDATE organization_profile
                SET org_name = ?, legal_status = ?, geographic_scope = ?, budget_scale = ?, 
                    focus_areas = ?, target_populations = ?, past_achievements = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
            """,
                (
                    org_name,
                    legal_status,
                    geographic_scope,
                    budget_scale,
                    focus_json,
                    target_json,
                    past_achievements,
                    existing["id"],
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO organization_profile 
                (org_name, legal_status, geographic_scope, budget_scale, focus_areas, target_populations, past_achievements)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
                (
                    org_name,
                    legal_status,
                    geographic_scope,
                    budget_scale,
                    focus_json,
                    target_json,
                    past_achievements,
                ),
            )

        conn.commit()
    print("✅ Organization profile configured.")


def add_member(
    full_name: str,
    email: str,
    telegram_chat_id: Optional[str] = None,
    role: str = "Member",
):
    """Adds or updates a team member for automated alerts."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO members (full_name, email, telegram_chat_id, role)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                full_name = excluded.full_name,
                telegram_chat_id = excluded.telegram_chat_id,
                role = excluded.role;
        """,
            (full_name, email, telegram_chat_id, role),
        )
        conn.commit()
    print(f"✅ Member added/updated: {full_name} ({email})")


def get_org_profile() -> Dict:
    """Fetches the organization profile for Gemini AI context construction."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM organization_profile LIMIT 1;")
        row = cursor.fetchone()
        if not row:
            return {}

        profile = dict(row)
        profile["focus_areas"] = json.loads(profile["focus_areas"])
        profile["target_populations"] = json.loads(profile["target_populations"])
        return profile


def get_active_members() -> List[Dict]:
    """Retrieves all active members for email and Telegram dispatching."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT full_name, email, telegram_chat_id, role FROM members WHERE is_active = 1;"
        )
        return [dict(row) for row in cursor.fetchall()]


# --- Execution Example ---
if __name__ == "__main__":
    init_db()

    # Seed Organization Profile Data
    upsert_org_profile(
        org_name="Ease Africa",
        legal_status="Registered Local Non-Governmental Organization (CSO)",
        geographic_scope="Ethiopia (Sub-Saharan Africa)",
        budget_scale="$10,000 - $250,000 USD",
        focus_areas=[
            "Maternal & Child Health",
            "Infectious Disease Control (TB, HIV, Malaria)",
            "Water, Sanitation, and Hygiene (WASH)",
            "Community Epidemiology & Health Data Analysis",
        ],
        target_populations=[
            "Rural women & infants",
            "Underserved pastoral communities",
            "Primary health care clinics",
        ],
        past_achievements=(
            "Successfully implemented 3 USAID and WHO community health grants. "
            "Improved maternal immunization tracking in rural districts using DHIS2 integration. "
            "Trained 150+ community health workers in disease surveillance."
        ),
    )

    # Seed Team Members
    add_member(
        full_name="Hailegiorgis Yirgu",
        email="hgyirgu1@gmail.com",
        telegram_chat_id="12121212",
        role="Grant Director",
    )
    add_member(
        full_name="Matyas Demesew",
        email="maqtyas@gmail.com",
        telegram_chat_id="0000000",
        role="Program Manager",
    )

    print("\n--- Current Loaded Profile ---")
    print(json.dumps(get_org_profile(), indent=2))