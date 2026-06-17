# AI Opportunity Radar

B2B buying-intent signal detection for AI automation agencies. Scans funding events, hiring signals, exec changes, tech stack shifts, and website updates — then scores and ranks companies by purchase readiness and generates personalised outreach copy.

## Stack

| Layer | Tech |
|---|---|
| Backend API | FastAPI + Python 3.11 |
| AI | Claude Haiku 4.5 (extraction) + Sonnet 4.6 (reasoning/copy) |
| Database | Supabase (PostgreSQL) |
| Frontend | Next.js 14 App Router + Tailwind CSS |
| Notifications | Resend (email) + Slack webhooks |
| Billing | Stripe Subscriptions |
| Scrapers | Bing News API, Apify (LinkedIn), Crunchbase RSS, Indeed RSS |

## Quick start

### 1. Database

Run `db/schema.sql` in your Supabase SQL editor. It creates all tables and seeds default signal weights.

### 2. Backend

```bash
cd opportunity-radar
cp .env.example .env
# Fill in all values in .env

pip install -r requirements.txt

# Run API + background scheduler together
python start.py

# Or CLI one-shot scan:
python main.py --domains acme.com,foocorp.io --min-score 65
```

### 3. Frontend

```bash
cd opportunity-radar/frontend
cp .env.local.example .env.local
# Set NEXT_PUBLIC_API_URL=http://localhost:8000

npm install
npm run dev
# Open http://localhost:3000
```

## Environment variables

See `.env.example` for the full list. Required keys:

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `SUPABASE_URL` | Supabase project settings |
| `SUPABASE_ANON_KEY` | Supabase project settings |
| `BING_API_KEY` | Azure portal (Bing Search v7) |
| `RESEND_API_KEY` | resend.com |
| `STRIPE_SECRET_KEY` | Stripe dashboard |
| `STRIPE_WEBHOOK_SECRET` | Stripe CLI: `stripe listen --forward-to localhost:8000/webhooks/stripe` |
| `STRIPE_PRICE_PILOT` | Stripe price ID for $497/month plan |
| `STRIPE_PRICE_GROWTH` | Stripe price ID for $997/month plan |
| `STRIPE_PRICE_SCALE` | Stripe price ID for $1997/month plan |

Optional:
- `APIFY_TOKEN` — LinkedIn job scraping (falls back to Indeed RSS without it)
- `APOLLO_API_KEY` — contact enrichment
- `BUILTWITH_API_KEY` — tech stack signals

## API endpoints

```
POST /customers/signup          Create account, returns API key (shown once)
POST /customers/checkout        Get Stripe checkout URL for plan upgrade
GET  /customers/me              Profile
PATCH /customers/me             Update specialty, verticals, Slack webhook

GET  /opportunities             List with ?min_score=65&status=new&limit=20&offset=0
GET  /opportunities/{id}        Full detail + outreach copy
PATCH /opportunities/{id}/status Update status (new/pursued/converted/not_relevant)
POST /opportunities/{id}/feedback Record outcome (the data moat endpoint)

POST /scan                      Trigger async scan for list of domains

POST /webhooks/stripe           Stripe webhook receiver

GET  /health
```

Auth: `X-API-Key: radar_...` header or `Authorization: Bearer radar_...`

## Architecture

```
Signals (Crunchbase RSS, Bing News, Indeed RSS, Apify, Website Monitor)
    ↓
SignalCollectionAgent  — Claude Haiku extracts structured signals
    ↓
ScoringAgent           — weighted formula → 0-100 score
    ↓
IntelligenceAgent      — Claude Sonnet derives likely needs + timing
    ↓
OutreachAgent          — Claude Sonnet writes email/LinkedIn/call opener
    ↓
Supabase               — persists everything
    ↓
FastAPI                — serves frontend + triggers Resend/Slack
    ↓
Next.js dashboard      — feed, analytics, feedback buttons
    ↓
LearningAgent (weekly) — re-weights signals from feedback outcomes
```

## Scoring formula

```
score = Σ(signal_weight × recency_multiplier × confidence) × company_fit_multiplier
```

Normalised 0–100. Recency curve: 1.0 (≤7d) → 0.85 (≤14d) → 0.65 (≤30d) → 0.40 (≤60d) → 0.15 (older).

Company fit multiplier (0.5–1.5) based on: employee count, B2B model, industry, tech stack.

## Scheduler (automatic)

| Schedule | Job |
|---|---|
| Daily 6 AM UTC | Scan all domains in `WATCHLIST_DOMAINS` env var |
| Monday 8 AM UTC | Email digest to all active customers |
| Sunday 3 AM UTC | Learning cycle — re-weight signals from feedback data |

## Plans

| Plan | Price | Opportunities/week |
|---|---|---|
| Pilot | $497/month | 10 |
| Growth | $997/month | 25 |
| Scale | $1997/month | Unlimited |

## Data moat

Every `POST /opportunities/{id}/feedback` call with `action=converted` and `deal_size_usd` writes to `opportunity_feedback`. The LearningAgent reads this table weekly and proposes signal weight updates. Over time the model gets calibrated to what signals actually predict closed deals for your specific customers.
