-- Table 1: Organization Profile
CREATE TABLE IF NOT EXISTS organization_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_name TEXT NOT NULL,
    legal_status TEXT NOT NULL,          -- e.g., "Registered Civil Society Organization (CSO)"
    geographic_scope TEXT NOT NULL,      -- e.g., "Ethiopia, Horn of Africa"
    budget_scale TEXT NOT NULL,           -- e.g., "$100k - $500k USD annual budget"
    focus_areas TEXT NOT NULL,           -- JSON string array: ["Maternal Health", "Infectious Diseases", "WASH"]
    target_populations TEXT NOT NULL,    -- JSON string array: ["Rural Women", "Children under 5"]
    past_achievements TEXT NOT NULL,     -- Key historical milestones and successfully completed grants
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 2: Team Member Contacts (Email & Telegram)
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    telegram_chat_id TEXT UNIQUE,         -- Telegram User ID or Group Chat ID
    role TEXT DEFAULT 'Member',           -- e.g., "Grant Manager", "Executive Director"
    is_active INTEGER DEFAULT 1,          -- 1 = Receive alerts, 0 = Disabled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 3: Grant Matches & AI Proposals (Prepared for Phase 3)
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