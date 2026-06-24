# Database Design — Opportunity Radar
Date: 2026-06-23 | Architect: database-architect skill

---

## Storage Engine

**PostgreSQL via Supabase** — correct choice for this domain. Rationale:
- Transactional signals and opportunities need ACID guarantees.
- Multi-tenant row isolation requires foreign keys + RLS, not eventual consistency.
- `JSONB` is appropriate for `tech_stack` (low cardinality, rarely queried inside) and `score_breakdown` (audit log, always read whole).
- No vector DB needed yet — similarity search on signals not required at current scale.
- No time-series DB needed — `detected_at` with a B-tree index is sufficient for the query volumes expected (<1M signals/month).

---

## ERD

```
customers 1──∞ opportunities ∞──1 companies
              |
              ∞
         outreach_packages
              
customers 1──∞ opportunity_feedback ∞──1 opportunities

companies 1──∞ signals
companies 1──∞ contacts

signal_weights (standalone calibration table)
```

---

## Schema Issues Found

### Critical

| # | Table | Issue |
|---|-------|-------|
| S1 | `opportunities` | `company_id` FK has no `ON DELETE CASCADE` — deleting a company orphans its opportunities |
| S2 | All tables | No Row-Level Security policies — any authenticated Supabase client can read all tenants' data |
| S3 | `customers` | Two `slack_webhook` columns (`slack_webhook` + `slack_webhook_url` from migration) — old column never dropped, confusing callers |
| S4 | `db/migrate.py` | Uses `exec_sql` RPC that doesn't exist in Supabase by default — migrations silently fail |

### High

| # | Table | Issue |
|---|-------|-------|
| H1 | `customers`, `opportunities`, `opportunity_feedback` | `plan`, `status`, `action` columns have no CHECK constraints — invalid values accepted silently |
| H2 | `signals`, `contacts`, `outreach_packages`, `opportunity_feedback`, `signal_weights` | Missing `updated_at` — violates schema contract, breaks audit trail |
| H3 | `customers` | No index on `stripe_customer_id` — `get_customer_by_stripe_id()` does a full table scan on every webhook |
| H4 | `customers` | No index on `status` — `list_active_customers()` scans entire table |
| H5 | `opportunity_feedback` | `deal_size_usd INT` overflow risk for deals >$2.1B; use BIGINT |

### Medium

| # | Table | Issue |
|---|-------|-------|
| M1 | `opportunities` | No index on `expires_at` — cleanup queries scan the whole table |
| M2 | `db/migrate.py` | No migration tracking table — running twice re-executes all migrations |
| M3 | `db/supabase_client.py` | `lru_cache` on URL/key getter means env var changes after startup are invisible |
| M4 | `db/repositories/customers.py` | `get_customer_by_email`, `get_customer`, `get_customer_by_stripe_id` use `.single()` — crashes on not-found instead of returning `None` |

---

## Index Strategy

| Index | Query it serves | Cost |
|-------|----------------|------|
| `idx_companies_domain` | Signal collection lookup by domain | Low write cost |
| `idx_companies_industry` | Filter by industry | Low |
| `idx_signals_company` | Load signals for a company | Low |
| `idx_signals_type` | Filter by signal type | Low |
| `idx_signals_detected_at DESC` | Recency sort | Low |
| `idx_contacts_company` | Load contacts for a company | Low |
| `idx_contacts_email` | Dedup contacts | Low |
| `idx_opportunities_score DESC` | Top opportunities list | Low |
| `idx_opportunities_status` | Filter by status | Low |
| `idx_opportunities_created DESC` | Recent opportunities | Low |
| `idx_opportunities_customer` | Tenant isolation | **MISSING in base schema, added in migrate.py** |
| **ADD: customers(status)** | `list_active_customers()` | Low |
| **ADD: customers(stripe_customer_id)** | Webhook lookups | Low |
| **ADD: opportunities(expires_at)** | Expiry cleanup | Low |
| **ADD: signal_weights(signal_key)** | Already has UNIQUE — covers lookup | None needed |

---

## Access Pattern Analysis

### Top-5 Patterns (by frequency)

1. **List opportunities for a customer** — `opportunities WHERE customer_id = ? AND opportunity_score >= ? ORDER BY opportunity_score DESC LIMIT 50`
   - Covered by: `idx_opportunities_customer` + `idx_opportunities_score`
   - Best as composite: `(customer_id, opportunity_score DESC)` — add in migration

2. **Get all signals for a company domain** — JOIN companies ON domain = ?, then signals WHERE company_id = ?
   - Covered by: `idx_companies_domain` → `idx_signals_company`

3. **List active customers (scheduler)** — `customers WHERE status = 'active'`
   - No index — add `idx_customers_status`

4. **Stripe webhook lookup** — `customers WHERE stripe_customer_id = ?`
   - No index — add `idx_customers_stripe`

5. **Learning feedback query** — `opportunity_feedback JOIN opportunities WHERE created_at >= ?`
   - Covered by `idx_feedback_opportunity` + `idx_opportunities_created`
