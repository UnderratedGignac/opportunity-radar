-- Migration 002 — Schema Hardening
-- Apply via Supabase SQL Editor or psql.
-- All changes are additive (expand phase) — safe for concurrent reads/writes.
-- Down migration at bottom.

-- ─── Migration tracking table (run this first, once) ─────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INT PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Guard: skip if already applied
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = 2) THEN
    RAISE NOTICE 'Migration 002 already applied — skipping';
    RETURN;
  END IF;
END $$;

-- ─── S1: Fix opportunities.company_id FK (add CASCADE) ───────────────────────
-- Expand: add new FK with cascade, drop old one
ALTER TABLE opportunities
    DROP CONSTRAINT IF EXISTS opportunities_company_id_fkey;

ALTER TABLE opportunities
    ADD CONSTRAINT opportunities_company_id_fkey
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE;

-- ─── S3: Drop duplicate slack_webhook column ──────────────────────────────────
-- The migrate.py migration added slack_webhook_url and copied data but never dropped old column.
ALTER TABLE customers
    DROP COLUMN IF EXISTS slack_webhook;

-- ─── H1: CHECK constraints on enum-like columns ──────────────────────────────
ALTER TABLE customers
    ADD CONSTRAINT chk_customers_plan
    CHECK (plan IN ('pilot', 'growth', 'scale'));

ALTER TABLE customers
    ADD CONSTRAINT chk_customers_status
    CHECK (status IN ('active', 'churned', 'paused'));

ALTER TABLE opportunities
    ADD CONSTRAINT chk_opportunities_status
    CHECK (status IN ('new', 'viewed', 'pursued', 'converted', 'not_relevant'));

ALTER TABLE opportunity_feedback
    ADD CONSTRAINT chk_feedback_action
    CHECK (action IN ('pursued', 'not_relevant', 'demo_booked', 'converted'));

-- ─── H2: Add missing updated_at columns ──────────────────────────────────────
ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE outreach_packages
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE opportunity_feedback
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- signal_weights already has last_updated — add canonical updated_at too
ALTER TABLE signal_weights
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- ─── H3 + H4 + M1: Missing indexes ──────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_customers_status
    ON customers(status);

CREATE INDEX IF NOT EXISTS idx_customers_stripe
    ON customers(stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_opportunities_expires
    ON opportunities(expires_at)
    WHERE expires_at IS NOT NULL;

-- Composite index for the most common tenant query (replaces two single-column scans)
CREATE INDEX IF NOT EXISTS idx_opportunities_customer_score
    ON opportunities(customer_id, opportunity_score DESC);

-- ─── H5: Widen deal_size_usd to BIGINT ───────────────────────────────────────
ALTER TABLE opportunity_feedback
    ALTER COLUMN deal_size_usd TYPE BIGINT;

-- ─── S2: Row-Level Security for multi-tenancy ────────────────────────────────
-- Enable RLS on the three tables that expose customer data.
-- Callers must set app.current_customer_id before querying.
-- The service-role key bypasses RLS (used by the API server).
ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_packages ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_feedback ENABLE ROW LEVEL SECURITY;

-- Policy: customers can only see their own opportunities
CREATE POLICY IF NOT EXISTS "customer_opportunities_isolation"
    ON opportunities
    FOR ALL
    USING (
        customer_id = current_setting('app.current_customer_id', TRUE)::UUID
        OR current_setting('app.bypass_rls', TRUE) = 'true'
    );

-- Policy: outreach is visible via the opportunity's customer
CREATE POLICY IF NOT EXISTS "customer_outreach_isolation"
    ON outreach_packages
    FOR ALL
    USING (
        opportunity_id IN (
            SELECT id FROM opportunities
            WHERE customer_id = current_setting('app.current_customer_id', TRUE)::UUID
        )
        OR current_setting('app.bypass_rls', TRUE) = 'true'
    );

-- Policy: feedback is per-customer
CREATE POLICY IF NOT EXISTS "customer_feedback_isolation"
    ON opportunity_feedback
    FOR ALL
    USING (
        customer_id = current_setting('app.current_customer_id', TRUE)::UUID
        OR current_setting('app.bypass_rls', TRUE) = 'true'
    );

-- ─── Record migration ─────────────────────────────────────────────────────────
INSERT INTO schema_migrations (version, name)
VALUES (2, 'schema_hardening')
ON CONFLICT (version) DO NOTHING;

-- ─── DOWN (rollback) ──────────────────────────────────────────────────────────
-- To revert:
--
-- ALTER TABLE opportunity_feedback ALTER COLUMN deal_size_usd TYPE INT;
-- ALTER TABLE customers DROP CONSTRAINT IF EXISTS chk_customers_plan;
-- ALTER TABLE customers DROP CONSTRAINT IF EXISTS chk_customers_status;
-- ALTER TABLE opportunities DROP CONSTRAINT IF EXISTS chk_opportunities_status;
-- ALTER TABLE opportunity_feedback DROP CONSTRAINT IF EXISTS chk_feedback_action;
-- ALTER TABLE signals DROP COLUMN IF EXISTS updated_at;
-- ALTER TABLE contacts DROP COLUMN IF EXISTS updated_at;
-- ALTER TABLE outreach_packages DROP COLUMN IF EXISTS updated_at;
-- ALTER TABLE opportunity_feedback DROP COLUMN IF EXISTS updated_at;
-- ALTER TABLE signal_weights DROP COLUMN IF EXISTS updated_at;
-- DROP INDEX IF EXISTS idx_customers_status;
-- DROP INDEX IF EXISTS idx_customers_stripe;
-- DROP INDEX IF EXISTS idx_opportunities_expires;
-- DROP INDEX IF EXISTS idx_opportunities_customer_score;
-- DROP POLICY IF EXISTS "customer_opportunities_isolation" ON opportunities;
-- DROP POLICY IF EXISTS "customer_outreach_isolation" ON outreach_packages;
-- DROP POLICY IF EXISTS "customer_feedback_isolation" ON opportunity_feedback;
-- ALTER TABLE opportunities DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE outreach_packages DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE opportunity_feedback DISABLE ROW LEVEL SECURITY;
-- DELETE FROM schema_migrations WHERE version = 2;
