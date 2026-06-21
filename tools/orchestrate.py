"""
AGY Orchestrator for Opportunity Radar.
Run: venv/Scripts/python tools/orchestrate.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tools.agy_bridge import run_task

PROJECT = "C:/Users/Elie/Ultimate Job/opportunity-radar"
P = PROJECT  # short alias used in prompts via .replace


def task(name: str, prompt: str, timeout: int = 180) -> bool:
    print(f"\n{'='*60}\nTASK: {name}\n{'='*60}")
    result = run_task(prompt, timeout=timeout, cwd=PROJECT)
    if result.ok:
        print(f"[OK] {result.text[:600]}")
    else:
        print(f"[FAIL] {result.error}")
    return result.ok


# ── helper to substitute PROJECT path into prompts ──────────────────
def p(prompt: str) -> str:
    return prompt.replace("<<PROJECT>>", PROJECT)


TASKS = [

# ══════════════════════════════════════════════════════════════
# WAVE 1 — Richer free signal sources
# ══════════════════════════════════════════════════════════════

("W1-T1: Integrate website monitor into signal collection", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Update agents/signal_collection_agent.py to also call the website monitor scraper.

Files to modify: agents/signal_collection_agent.py

What to do:
1. At the top, add: from scrapers.website_monitor import check_website
2. In _collect_for_domain(), add self._scrape_website(domain) to the tasks list
3. Add method _scrape_website(self, domain: str) -> list[Signal]:
   - Call: results = await check_website(domain)
   - check_website returns list[dict] with keys: signal_type, detail, source_url, confidence
   - Convert each dict to Signal: try SignalType(item["signal_type"]) except ValueError use SignalType.WEBSITE_CHANGE
   - Return list of Signal objects
   - Wrap in try/except, log warning on failure, return []

Constraints:
- Only modify agents/signal_collection_agent.py
- Keep all existing methods intact

Verification: Report files changed and confirm _scrape_website method exists.
""")),

("W1-T2: Add HackerNews Algolia API as free signal source", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Add HackerNews search as a signal source in agents/signal_collection_agent.py.

Files to modify: agents/signal_collection_agent.py

What to do:
1. Add method _scrape_hackernews(self, domain: str) -> list[Signal]:
   - company_name = domain.split(".")[0].replace("-", " ").title()
   - company_encoded = urllib.parse.quote(company_name)
   - URL: "https://hn.algolia.com/api/v1/search?query=" + company_encoded + "&tags=story&hitsPerPage=5"
   - Make async GET with aiohttp (10s timeout)
   - If status != 200, return []
   - Parse JSON response: hits = data["hits"]
   - For each hit in hits[:5]: build text = hit.get("title","") + " " + (hit.get("url") or "")
     then call: signals = await self._extract_signals(text, hit.get("url",""), "hackernews", domain)
     extend the main signals list
   - Return all signals
   - Wrap in try/except, log warning on error, return []

2. In _collect_for_domain(), add self._scrape_hackernews(domain) to the tasks list

Constraints: urllib.parse already imported. Don't modify any other file.
Verification: Confirm _scrape_hackernews exists and is called in _collect_for_domain.
""")),

("W1-T3: Rewrite Apollo stub as free email pattern discovery", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Rewrite scrapers/apollo.py with free email pattern inference (no API).

Files to modify: scrapers/apollo.py

Rewrite the entire file with this content (write it exactly):

\"\"\"Contact discovery via email pattern inference — no API key required.\"\"\"
from __future__ import annotations
import logging
logger = logging.getLogger("radar.scraper.contacts")

_SALES_PERSONAS = [
    ("VP of Sales", "Alex", "Johnson"),
    ("Head of Revenue", "Jordan", "Smith"),
    ("CRO", "Sam", "Williams"),
    ("CEO", "Chris", "Davis"),
    ("Director of Sales", "Taylor", "Brown"),
]

async def get_contacts(domain: str) -> list[dict]:
    contacts = []
    for title, first, last in _SALES_PERSONAS:
        f, l = first.lower(), last.lower()
        patterns = [
            f"{f}.{l}@{domain}",
            f"{f}@{domain}",
            f"{f}{l}@{domain}",
            f"{f[0]}{l}@{domain}",
        ]
        contacts.append({
            "first_name": first,
            "last_name": last,
            "title": title,
            "domain": domain,
            "email_patterns": patterns,
            "most_likely_email": patterns[0],
            "confidence": 0.4,
            "source": "pattern_inference",
        })
    logger.debug("Pattern-inferred %d contacts for %s", len(contacts), domain)
    return contacts

Write that file exactly. Do not add anything else.
Verification: Report file written.
""")),

("W1-T4: Add PR Newswire and acquisition news RSS sources", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Add two more free Google News RSS searches to agents/signal_collection_agent.py.

Files to modify: agents/signal_collection_agent.py

What to do:
1. Add method _scrape_acquisitions(self, domain: str) -> list[Signal]:
   - company_name = domain.split(".")[0].replace("-", " ").title()
   - query = '"' + company_name + '" (acquired OR acquires OR merger OR IPO OR "went public" OR "strategic investment")'
   - encoded = urllib.parse.quote(query)
   - url = "https://news.google.com/rss/search?q=" + encoded + "&hl=en-US&gl=US&ceid=US:en"
   - Fetch with aiohttp (10s timeout), parse with _parse_rss()
   - Take first 3 items, call _extract_signals on each title+description
   - Return signals, wrap in try/except log warning

2. Add method _scrape_prnewswire(self, domain: str) -> list[Signal]:
   - company_name = domain.split(".")[0].replace("-", " ").title()
   - query = '"' + company_name + '" site:businesswire.com OR site:prnewswire.com'
   - encoded = urllib.parse.quote(query)
   - url = "https://news.google.com/rss/search?q=" + encoded + "&hl=en-US&gl=US&ceid=US:en"
   - Fetch, parse RSS, take first 3 items, extract signals
   - Return signals, wrap in try/except log warning

3. In _collect_for_domain(), add both new methods to the tasks list.

Constraints: _parse_rss and _extract_signals already exist. urllib.parse imported.
Verification: Confirm both methods exist and are in _collect_for_domain tasks list.
""")),

# ══════════════════════════════════════════════════════════════
# WAVE 2 — API hardening
# ══════════════════════════════════════════════════════════════

("W2-T1: Add signal deduplication and recent opportunity check", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Add signal deduplication and idempotency to prevent duplicate DB rows.

Files to modify: db/repositories/opportunities.py, api/routers/scan.py

Part 1 - Add to db/repositories/opportunities.py (at the end of the file):

async def get_recent_opportunity(company_id: str) -> dict | None:
    \"\"\"Return existing opportunity for company created in last 24h, or None.\"\"\"
    import datetime
    from db.supabase_client import get_client
    client = get_client()
    try:
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).isoformat()
        result = client.table("opportunities").select("id, created_at").eq("company_id", company_id).gte("created_at", cutoff).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None

Part 2 - In api/routers/scan.py, in _run_scan_and_persist():
- Add these imports at top of scan.py if not present: from db.repositories.opportunities import get_recent_opportunity
- In the for loop over packages, after upsert_company, add:
    existing = await get_recent_opportunity(company_id)
    if existing:
        continue  # Skip — already scanned this company recently

- Also deduplicate signals list before persisting: add at top of the for pkg loop:
    seen_sigs = set()
    # (then inside signal inserts, check (domain, type, detail) tuple)

Constraints:
- get_recent_opportunity should return None if Supabase is not available (wrap in try/except)
- Keep all existing function signatures

Verification: Report files changed.
""")),

("W2-T2: Add rate limiting to scan endpoint", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Add in-memory rate limiting and domain validation to api/routers/scan.py.

Files to modify: api/routers/scan.py

What to add at the top of the file (after existing imports):

import time
import re as _re
from collections import defaultdict

_scan_counts: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 600   # 10 minutes
_RATE_MAX = 5        # max 5 scans per window


def _rate_check(customer_id: str) -> bool:
    now = time.time()
    window_start = now - _RATE_WINDOW
    _scan_counts[customer_id] = [t for t in _scan_counts[customer_id] if t > window_start]
    if len(_scan_counts[customer_id]) >= _RATE_MAX:
        return False
    _scan_counts[customer_id].append(now)
    return True


In trigger_scan(), after the len check, add:
    from fastapi import HTTPException
    if not _rate_check(customer.get("id", "anon")):
        raise HTTPException(status_code=429, detail="Rate limit: max 5 scans per 10 minutes")

    valid = [d.strip().lower() for d in payload.domains
             if _re.match(r'^[a-z0-9][a-z0-9\\-\\.]+\\.[a-z]{2,}$', d.strip().lower())]
    if not valid:
        raise HTTPException(400, "No valid domains. Use format: example.com")
    payload.domains = valid

Constraints: time and collections are stdlib. Keep existing HTTPException imports.
Verification: Confirm _rate_check exists and is called in trigger_scan.
""")),

("W2-T3: Add CSV export endpoint", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Add GET /opportunities/export endpoint that returns CSV download.

Files to modify: api/routers/opportunities.py

What to do:
1. Add these imports near the top: import csv, import io
2. Add: from fastapi.responses import StreamingResponse

3. Add this route BEFORE the existing @router.get("") route (it must come first):

@router.get("/export")
async def export_opps(
    customer: Customer,
    min_score: int = Query(60, ge=0, le=100),
):
    if not _supabase_ready():
        opps = [o for o in _MOCK_OPPORTUNITIES if o["opportunity_score"] >= min_score]
    else:
        from db.repositories.opportunities import list_opportunities
        opps = await list_opportunities(min_score=min_score, limit=500)

    output = io.StringIO()
    fieldnames = ["company_name","company_domain","opportunity_score","confidence_score",
                  "status","timing_rationale","created_at",
                  "email_subject","email_body","linkedin_message","call_opener"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for opp in opps:
        raw_outreach = opp.get("outreach") or {}
        if isinstance(raw_outreach, list):
            raw_outreach = raw_outreach[0] if raw_outreach else {}
        row = {k: opp.get(k, "") for k in fieldnames}
        row["email_subject"] = raw_outreach.get("email_subject", "")
        row["email_body"] = (raw_outreach.get("email_body", "") or "").replace("\\n", " ")
        row["linkedin_message"] = raw_outreach.get("linkedin_message", "")
        row["call_opener"] = raw_outreach.get("call_opener", "")
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=opportunities.csv"},
    )

Constraints:
- csv and io are stdlib
- /export route must be registered before /{opp_id} to avoid route conflict
Verification: Confirm /export route is above /{opp_id} in the file.
""")),

("W2-T4: Implement Stripe webhook handler", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Implement billing/webhooks.py and add /webhooks/stripe route to api/main.py.

Files to modify: billing/webhooks.py, api/main.py

Part 1 - Rewrite billing/webhooks.py:

\"\"\"Stripe webhook handler.\"\"\"
from __future__ import annotations
import hashlib, hmac, logging, os, time, json
logger = logging.getLogger("radar.billing.webhooks")

def verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    try:
        parts = {k: v for part in sig_header.split(",") for k, v in [part.split("=", 1)]}
        ts = int(parts.get("t", "0"))
        if abs(time.time() - ts) > 300:
            return False
        signed = f"{ts}.{payload.decode()}"
        expected = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, parts.get("v1", ""))
    except Exception as e:
        logger.warning("Sig verify failed: %s", e)
        return False

async def handle_checkout_completed(data: dict) -> None:
    session = data.get("object", {})
    email = session.get("customer_details", {}).get("email", "")
    plan = session.get("metadata", {}).get("plan", "pilot")
    logger.info("Checkout complete: %s plan=%s", email, plan)

async def handle_subscription_deleted(data: dict) -> None:
    sub = data.get("object", {})
    logger.info("Subscription cancelled: %s", sub.get("customer", ""))

_HANDLERS = {
    "checkout.session.completed": handle_checkout_completed,
    "customer.subscription.deleted": handle_subscription_deleted,
}

async def process_event(event: dict) -> str:
    t = event.get("type", "")
    h = _HANDLERS.get(t)
    if h:
        await h(event.get("data", {}))
        return f"handled:{t}"
    return f"ignored:{t}"

Part 2 - In api/main.py, add after the existing router includes:

from fastapi import Request, Response
import json as _json, os as _os

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = _os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if secret:
        from billing.webhooks import verify_stripe_signature
        if not verify_stripe_signature(payload, sig, secret):
            return Response(status_code=400, content="Invalid signature")
    try:
        event = _json.loads(payload)
        from billing.webhooks import process_event
        result = await process_event(event)
        return {"received": True, "result": result}
    except Exception as e:
        return Response(status_code=400, content=str(e))

Constraints: No new pip packages needed. Webhook must not require X-API-Key.
Verification: Report files changed.
""")),

("W2-T5: Add startup validation and scan status tracking", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: (1) Add startup env validation to start.py, (2) Add scan status tracking to api/routers/scan.py.

Files to modify: start.py, api/routers/scan.py

Part 1 - In start.py, add before the uvicorn.run() call:

def _check_env():
    import os
    checks = [
        ("SUPABASE_URL", "Database not configured"),
        ("SUPABASE_KEY", "Database key missing"),
    ]
    print("\\n[Startup Check]")
    for key, msg in checks:
        val = os.getenv(key, "")
        if not val or "xxx" in val or "your-project" in val:
            print(f"  WARN {key}: {msg} — using mock data")
        else:
            print(f"  OK   {key} configured")
    import subprocess
    agy = subprocess.run(["agy.exe", "--help"], capture_output=True)
    print(f"  {'OK' if agy.returncode == 0 else 'WARN'} AGY worker: {'available' if agy.returncode == 0 else 'not found'}")
    print()

Call _check_env() before uvicorn.run() in the main execution block.

Part 2 - In api/routers/scan.py, add at the top (after imports):

import uuid as _uuid
from datetime import datetime as _dt

_scans: dict[str, dict] = {}

def _new_scan(domains: list[str]) -> str:
    sid = _uuid.uuid4().hex[:12]
    _scans[sid] = {
        "id": sid, "domains": domains, "status": "running",
        "started_at": _dt.utcnow().isoformat(),
        "completed_at": None, "found": 0, "error": None,
    }
    return sid

def _finish_scan(sid: str, found: int = 0, error: str | None = None) -> None:
    if sid in _scans:
        _scans[sid].update({
            "status": "error" if error else "complete",
            "completed_at": _dt.utcnow().isoformat(),
            "found": found, "error": error,
        })

Modify _run_scan_and_persist() to:
- Accept optional scan_id: str = "" parameter
- Count inserted opportunities: count = 0, increment count after each successful insert
- At the end call: _finish_scan(scan_id, found=count) in a finally block
- On exception in the outer try: call _finish_scan(scan_id, error=str(e))

Modify trigger_scan():
- Add: scan_id = _new_scan(payload.domains)
- Pass scan_id to background task
- Return scan_id in response dict

Add new endpoint:
@router.get("/status/{scan_id}")
async def get_scan_status(scan_id: str, customer: Customer):
    s = _scans.get(scan_id)
    if not s:
        raise HTTPException(404, "Scan not found")
    return s

Verification: Report files changed. Confirm _new_scan and _finish_scan exist.
""")),

# ══════════════════════════════════════════════════════════════
# WAVE 3 — Frontend
# ══════════════════════════════════════════════════════════════

("W3-T1: Upgrade main feed with filters, feedback buttons, textarea", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Improve frontend/app/page.tsx with signal type filter, quick feedback buttons, CSV export.

Files to modify: frontend/app/page.tsx, frontend/lib/api.ts

Part 1 - In frontend/lib/api.ts:
1. In the opportunities.list call, support signal_type param:
   Add: if (params?.signal_type) q.set('signal_type', params.signal_type)
   Update the params type to include: signal_type?: string
2. Add export function to api.customers or top level:
   export: (minScore: number) => `http://localhost:8000/opportunities/export?min_score=${minScore}`

Part 2 - In frontend/app/page.tsx:
1. Change the single-line domain input to a textarea:
   - Replace the <input> element with <textarea rows={3} ...>
   - On scan, split by newlines and commas: const domains = domainInput.split(/[\\n,]+/).map(d => d.trim()).filter(Boolean)
   - Keep the placeholder text helpful: "stripe.com\\nhubspot.com\\nsalesforce.com"

2. Add signal type filter dropdown above the opportunity grid (after FilterBar):
   - Add state: const [signalFilter, setSignalFilter] = useState('')
   - Add <select> with options: all types, funding, hiring, exec_change, tech_change, website_change
   - Filter the displayed opportunities client-side:
     const displayedOpps = signalFilter
       ? opps.filter(o => o.signals?.some(s => s.signal?.type === signalFilter || s.type === signalFilter))
       : opps

3. Add quick feedback buttons on each opportunity card:
   - After the OpportunityCard component (or inside the map), add two small buttons:
     <button onClick={() => { api.opportunities.feedback(opp.id, {action:'pursued'}); setDismissed(prev => new Set([...prev, opp.id])) }}>Pursue</button>
     <button onClick={() => { api.opportunities.feedback(opp.id, {action:'not_relevant'}); setDismissed(prev => new Set([...prev, opp.id])) }}>Not relevant</button>
   - Add state: const [dismissed, setDismissed] = useState<Set<string>>(new Set())
   - Filter displayed: .filter(o => !dismissed.has(o.id))

4. Add CSV export button near the scan button area:
   const downloadCSV = async () => {
     const key = typeof window !== 'undefined' ? localStorage.getItem('radar_api_key') || '' : ''
     const res = await fetch('http://localhost:8000/opportunities/export?min_score=' + minScore, {headers: {'X-API-Key': key}})
     if (!res.ok) return
     const blob = await res.blob()
     const url = URL.createObjectURL(blob)
     const a = document.createElement('a'); a.href = url; a.download = 'opportunities.csv'; a.click()
     URL.revokeObjectURL(url)
   }
   Add button: <button onClick={downloadCSV}>Export CSV</button>

Constraints:
- Keep existing SWR fetch and refresh logic
- Style new elements consistently with existing Tailwind classes (text-slate-400, bg-slate-800, etc.)
- dismissed state resets on page refresh (no persistence needed)

Verification: Report files changed and list the 4 improvements added.
""")),

("W3-T2: Make settings page functional with Slack webhook save", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Make Settings page functional — save Slack webhook to backend.

Files to modify: api/routers/customers.py, db/repositories/customers.py, frontend/app/settings/page.tsx, frontend/lib/api.ts

Part 1 - In api/routers/customers.py, add:

class UpdateProfilePayload(BaseModel):
    slack_webhook_url: str | None = None
    agency_specialty: str | None = None

@router.patch("/me")
async def update_profile(payload: UpdateProfilePayload, customer: Customer):
    if not _supabase_ready():
        return {"ok": True, "dev_mode": True}
    from db.repositories.customers import update_customer
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    await update_customer(customer["id"], updates)
    return {"ok": True}

@router.post("/slack-test")
async def test_slack_webhook(payload: dict, customer: Customer):
    webhook_url = payload.get("webhook_url", "")
    if not webhook_url.startswith("https://hooks.slack.com/"):
        raise HTTPException(400, "Invalid Slack webhook URL")
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(webhook_url, json={"text": "Opportunity Radar test alert!"}) as resp:
            return {"ok": resp.status == 200}

Check if _supabase_ready function exists in customers.py; if not, add it:
def _supabase_ready() -> bool:
    import os
    url = os.getenv("SUPABASE_URL", "")
    return bool(url) and "xxx" not in url and url != "https://your-project.supabase.co"

Part 2 - In db/repositories/customers.py, add:

async def update_customer(customer_id: str, updates: dict) -> dict:
    from db.supabase_client import get_client
    client = get_client()
    try:
        result = client.table("customers").update(updates).eq("id", customer_id).execute()
        return result.data[0] if result.data else {}
    except Exception:
        return {}

Part 3 - In frontend/lib/api.ts, add to the customers section:
update: (data: {slack_webhook_url?: string; agency_specialty?: string}) =>
  req<{ok: boolean}>('/customers/me', {method: 'PATCH', body: JSON.stringify(data)}),
testSlack: (webhookUrl: string) =>
  req<{ok: boolean}>('/customers/slack-test', {method: 'POST', body: JSON.stringify({webhook_url: webhookUrl})}),

Part 4 - In frontend/app/settings/page.tsx:
- Add slackSaved state: const [slackSaved, setSlackSaved] = useState<'idle'|'saving'|'saved'|'error'>('idle')
- Add slackTestResult state: const [slackTestResult, setSlackTestResult] = useState<string|null>(null)
- Populate slack from customer data: useEffect(() => { if ((customer as any)?.slack_webhook_url) setSlack((customer as any).slack_webhook_url) }, [customer])
- Make "Save" button for Slack: onClick calls api.customers.update({slack_webhook_url: slack}) and sets slackSaved='saved'
- Add "Test" button next to Save: calls api.customers.testSlack(slack), shows "OK" or "Failed" in slackTestResult state
- Add agency specialty field: input bound to specialty, Save calls api.customers.update({agency_specialty: specialty})

Verification: Report files changed.
""")),

("W3-T3: Complete analytics page with signal performance table", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Enhance frontend/app/analytics/page.tsx with signal performance metrics.

Files to modify: frontend/app/analytics/page.tsx

What to add to the existing analytics page (which already has KPI row and signal breakdown):

1. Add a "Signal Performance" table below the existing charts:
   Build a table showing for each signal type: total signals, opportunities where that signal appeared, pursuit rate

   Use this logic (client-side computation from the opps data):
   const signalPerf: Record<string, {count: number; pursued: number; converted: number}> = {}
   for (const opp of opps) {
     const isPursued = ['pursued','demo_booked','converted'].includes(opp.status)
     const isConverted = opp.status === 'converted'
     for (const s of (opp.signals || [])) {
       const type = s.signal?.type || s.type || 'unknown'
       if (!signalPerf[type]) signalPerf[type] = {count: 0, pursued: 0, converted: 0}
       signalPerf[type].count++
       if (isPursued) signalPerf[type].pursued++
       if (isConverted) signalPerf[type].converted++
     }
   }

   Render as a simple HTML table with columns: Signal Type | Occurrences | Pursued | Pursuit Rate
   Style with dark theme (bg-slate-800, text-slate-300, border-slate-700)

2. Add a "Top Opportunities" section: list the top 5 highest-scored opportunities with links to their detail pages

3. Add a "Recent Activity" section: last 5 opportunities ordered by created_at desc, showing company name + score + status badge

Constraints:
- All data comes from the existing opps array — no new API calls
- Keep the existing StatCard component and top KPI row
- Use Tailwind classes consistent with the rest of the app

Verification: Report changes made.
""")),

# ══════════════════════════════════════════════════════════════
# WAVE 4 — Quality
# ══════════════════════════════════════════════════════════════

("W4-T1: Add structured logging middleware to FastAPI", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Add request ID middleware and improve /health endpoint in api/main.py.

Files to modify: api/main.py

What to add:

1. Add imports at top: import uuid, import time
2. Add a middleware (before the router includes):

@app.middleware("http")
async def log_requests(request: Request, call_next):
    req_id = uuid.uuid4().hex[:8]
    start = time.time()
    response = await call_next(request)
    ms = round((time.time() - start) * 1000)
    import logging
    logging.getLogger("radar.http").info(
        "%s %s -> %s (%dms) [%s]",
        request.method, request.url.path, response.status_code, ms, req_id
    )
    response.headers["X-Request-Id"] = req_id
    return response

Note: Add `from fastapi import Request` import if not already there.

3. Improve /health to include AGY status:

@app.get("/health")
async def health():
    import subprocess
    try:
        agy = subprocess.run(["agy.exe", "--help"], capture_output=True, timeout=3)
        agy_ok = agy.returncode == 0
    except Exception:
        agy_ok = False
    return {
        "status": "ok",
        "service": "opportunity-radar",
        "agy_worker": "available" if agy_ok else "unavailable",
    }

Constraints: uuid and time are stdlib. Do not break existing routes.
Verification: Report files changed.
""")),

("W4-T2: Tune scoring agent signal weights", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Read agents/scoring_agent.py and improve the signal weights and normalization.

Files to modify: agents/scoring_agent.py

First, read the current _SIGNAL_WEIGHTS dict. Then:

1. Add these missing weight entries to _SIGNAL_WEIGHTS:
   - "enterprise": 14 (website change showing enterprise tier)
   - "pricing": 13 (pricing page update)
   - "schedule a demo": 12
   - "we're hiring": 10
   - "acquisition": 30
   - "acquired": 28
   - "merger": 25
   - "ipo": 32
   - "went public": 30
   - "strategic investment": 20
   - "customer success manager": 18
   - "demand generation": 16
   - "chief of staff": 14
   - "head of growth": 20
   - "series c": 40
   - "series d": 38
   - "pre-seed": 18

2. Improve _recency_multiplier() to use more breakpoints:
   - <= 3 days: 1.0
   - <= 7 days: 0.95
   - <= 14 days: 0.80
   - <= 30 days: 0.60
   - <= 60 days: 0.35
   - older: 0.15

3. In _score_signals(), add source diversity bonus:
   After computing raw_score, count unique source_types in signals.
   If len(unique_source_types) >= 3: multiply raw_score by 1.1

4. Fix normalization: replace the arbitrary /1.2 with:
   final_score = min(100, int(raw_score * 0.75))
   (The 0.75 factor naturally caps single-signal scores below 30 while multi-signal companies can reach 80+)

Constraints:
- Keep 0-100 integer range
- Keep existing function signatures

Verification: List the new weight entries added and confirm new normalization formula.
""")),

("W4-T3: Add bulk CSV upload endpoint for domains", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Add POST /scan/bulk endpoint for CSV file upload.

Files to modify: api/routers/scan.py

Add this to api/routers/scan.py:

1. Add imports at top: from fastapi import UploadFile, File
   and: import csv as _csv, import io as _io

2. Add endpoint:

@router.post("/bulk")
async def trigger_bulk_scan(
    customer: Customer,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    min_score: int = 20,
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "Must upload a .csv file")

    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    reader = _csv.reader(_io.StringIO(text))

    import re as _re2
    domains = []
    for row in reader:
        if not row:
            continue
        domain = row[0].strip().lower().removeprefix("http://").removeprefix("https://").split("/")[0]
        if _re2.match(r'^[a-z0-9][a-z0-9\\-\\.]+\\.[a-z]{2,}$', domain):
            domains.append(domain)
        if len(domains) >= 50:
            break

    if not domains:
        raise HTTPException(400, "No valid domains in CSV. Column 1 should have: stripe.com, hubspot.com etc.")

    scan_id = _new_scan(domains)
    background.add_task(_run_scan_and_persist, domains, min_score, customer, scan_id)
    return {
        "status": "scanning",
        "scan_id": scan_id,
        "domains_queued": len(domains),
        "preview": domains[:5],
        "message": f"Bulk scan started for {len(domains)} domains.",
    }

Constraints: UploadFile and File come from fastapi. csv and io are stdlib.
Verification: Report file changed and confirm /scan/bulk endpoint exists.
""")),

("W4-T4: Add multi-tenancy customer_id filtering", p("""
You are a code worker for the AI Opportunity Radar at <<PROJECT>>.

Task: Fix multi-tenancy — filter opportunities by customer_id.

Files to modify: api/routers/scan.py, api/routers/opportunities.py, db/repositories/opportunities.py

Part 1 - In api/routers/scan.py, in _run_scan_and_persist():
- After the function signature, add: customer_id = customer.get("id", "")
- In the insert_opportunity() call, add "customer_id": customer_id to the dict

Part 2 - In db/repositories/opportunities.py:
- In list_opportunities(), add optional parameter: customer_id: str | None = None
- In the query chain, add (after the existing filters, before .execute()):
  if customer_id and customer_id != "dev":
      query = query.eq("customer_id", customer_id)

Part 3 - In api/routers/opportunities.py, in list_opps():
- Add: cust_id = customer.get("id")
- Pass customer_id=cust_id to list_opportunities(...)

Constraints:
- If customer["id"] == "dev" (from DEV_API_KEY bypass), do NOT filter — show all records
- Default to None (no filter) if customer_id not provided
- list_opportunities must remain backward-compatible (default customer_id=None means no filter)

Verification: Report files changed.
""")),

]


def main():
    print(f"Opportunity Radar — AGY Orchestration")
    print(f"Project: {PROJECT}")
    print(f"Total tasks: {len(TASKS)}")

    results = []
    for i, (name, prompt) in enumerate(TASKS, 1):
        print(f"\n[{i}/{len(TASKS)}] {name}")
        ok = task(name, prompt, timeout=180)
        results.append((name, ok))
        if not ok:
            print("  WARNING: failed — continuing")

    print("\n" + "="*60)
    print("ORCHESTRATION COMPLETE")
    print("="*60)
    for name, ok in results:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")

    passed = sum(1 for _, ok in results if ok)
    print(f"\n{passed}/{len(results)} tasks completed")


if __name__ == "__main__":
    main()
