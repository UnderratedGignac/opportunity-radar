-- AI Opportunity Radar — PostgreSQL Schema (Supabase-ready)
-- Deploy to: Supabase SQL editor or `psql -f schema.sql`

-- ─── COMPANIES ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    domain          TEXT UNIQUE NOT NULL,
    industry        TEXT,
    employee_count  INT,
    revenue_range   TEXT,           -- '<1M','1-10M','10-50M','50M+'
    hq_city         TEXT,
    hq_country      TEXT,
    tech_stack      JSONB DEFAULT '[]',
    linkedin_url    TEXT,
    crunchbase_url  TEXT,
    business_model  TEXT,           -- 'b2b','b2c','marketplace'
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_companies_domain    ON companies(domain);
CREATE INDEX IF NOT EXISTS idx_companies_industry  ON companies(industry);

-- ─── SIGNALS ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID REFERENCES companies(id) ON DELETE CASCADE,
    signal_type     TEXT NOT NULL,  -- 'funding','hiring','exec_change','tech_change','website_change','news'
    signal_detail   TEXT NOT NULL,
    source_url      TEXT,
    source_type     TEXT,           -- 'news','job_board','crunchbase','website'
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confidence      FLOAT DEFAULT 0.5,
    raw_data        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signals_company      ON signals(company_id);
CREATE INDEX IF NOT EXISTS idx_signals_type         ON signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_detected_at  ON signals(detected_at DESC);

-- ─── CONTACTS ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS contacts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID REFERENCES companies(id) ON DELETE CASCADE,
    first_name          TEXT,
    last_name           TEXT,
    title               TEXT,
    email               TEXT,
    linkedin_url        TEXT,
    is_decision_maker   BOOLEAN DEFAULT FALSE,
    source              TEXT DEFAULT 'apollo',  -- 'apollo','linkedin','manual'
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_email   ON contacts(email);

-- ─── OPPORTUNITIES ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunities (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID REFERENCES companies(id),
    customer_id         UUID REFERENCES customers(id),   -- which agency owns this opportunity
    opportunity_score   INT NOT NULL CHECK (opportunity_score BETWEEN 0 AND 100),
    confidence_score    INT NOT NULL CHECK (confidence_score BETWEEN 0 AND 100),
    likely_needs        TEXT[] DEFAULT '{}',
    decision_maker_titles TEXT[] DEFAULT '{}',
    timing_rationale    TEXT,
    score_breakdown     JSONB DEFAULT '[]',
    status              TEXT DEFAULT 'new',  -- 'new','viewed','pursued','converted','not_relevant'
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days'
);
CREATE INDEX IF NOT EXISTS idx_opportunities_score    ON opportunities(opportunity_score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_status   ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opportunities_created  ON opportunities(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_customer ON opportunities(customer_id);

-- MIGRATION (run once in Supabase SQL editor if table already exists):
-- ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id);
-- CREATE INDEX IF NOT EXISTS idx_opportunities_customer ON opportunities(customer_id);

-- ─── OUTREACH ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outreach_packages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id  UUID REFERENCES opportunities(id) ON DELETE CASCADE,
    email_subject   TEXT,
    email_body      TEXT,
    linkedin_message TEXT,
    call_opener     TEXT,
    key_hook        TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── CUSTOMERS ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_name         TEXT NOT NULL,
    owner_name          TEXT,
    email               TEXT UNIQUE NOT NULL,
    plan                TEXT DEFAULT 'pilot',   -- 'pilot','growth','scale'
    mrr_cents           INT DEFAULT 0,
    target_verticals    TEXT[] DEFAULT '{}',
    target_signals      TEXT[] DEFAULT '{}',
    agency_specialty    TEXT,
    slack_webhook       TEXT,
    api_key_hash        TEXT UNIQUE,
    stripe_customer_id  TEXT,
    status              TEXT DEFAULT 'active',  -- 'active','churned','paused'
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    churned_at          TIMESTAMPTZ
);

-- ─── FEEDBACK (the moat) ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunity_feedback (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id     UUID REFERENCES customers(id),
    opportunity_id  UUID REFERENCES opportunities(id),
    action          TEXT NOT NULL,  -- 'pursued','not_relevant','demo_booked','converted'
    deal_size_usd   INT,            -- filled when action='converted'
    days_to_close   INT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feedback_opportunity ON opportunity_feedback(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_feedback_customer    ON opportunity_feedback(customer_id);
CREATE INDEX IF NOT EXISTS idx_feedback_action      ON opportunity_feedback(action);

-- ─── SIGNAL WEIGHTS (updated by Learning Agent) ───────────────────────────────
CREATE TABLE IF NOT EXISTS signal_weights (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_key      TEXT UNIQUE NOT NULL,  -- e.g. 'funding.series_a', 'hiring.sdr'
    base_weight     FLOAT NOT NULL DEFAULT 15.0,
    last_updated    TIMESTAMPTZ DEFAULT NOW(),
    update_rationale TEXT,
    sample_size     INT DEFAULT 0          -- how many outcomes informed this weight
);

-- Seed default weights
INSERT INTO signal_weights (signal_key, base_weight) VALUES
    ('funding.series_a', 35),
    ('funding.series_b', 30),
    ('funding.seed', 25),
    ('exec_change.vp_sales', 35),
    ('exec_change.cmo', 30),
    ('exec_change.coo', 25),
    ('hiring.sdr', 28),
    ('hiring.ae', 25),
    ('hiring.marketing', 22),
    ('tech_change.crm', 28),
    ('tech_change.automation', 20),
    ('website_change.pricing', 15),
    ('news.funding_mention', 20)
ON CONFLICT (signal_key) DO NOTHING;
