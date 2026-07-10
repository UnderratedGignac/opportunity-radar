"""MENA freelance-lead discovery via LinkedIn's public jobs-guest endpoint.

The signal: a Gulf/Lebanon company that just posted an AUTOMATABLE role
(data entry, admin, booking, support, bookkeeping, social) has admitted a
manual pain, allocated budget, and named the exact task — the perfect moment
for a freelance automation pitch.

Pipeline (all plain HTTP, verified 2026-07-10):
  1. LinkedIn jobs-guest search  -> named company + LinkedIn company page + role
  2. drop anonymous / staffing-agency / big-enterprise rows
  3. LinkedIn company page        -> real website (via the redirect link)
  4. scrapers.email_finder        -> verified contact email (done elsewhere)
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import shutil
import urllib.parse

import aiohttp

logger = logging.getLogger("radar.scraper.mena_jobs")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0; eliehaddadh1@gmail.com)"}
_CHROME_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = aiohttp.ClientTimeout(total=15)


def _normalize_company_url(url: str) -> str:
    """Force the www. subdomain: country subdomains (ae./lb./it....) serve
    localized (e.g. Arabic) field labels that the English-label parser can't
    read, even though the underlying data is identical."""
    return re.sub(r'https://[a-z]{2,3}\.linkedin\.com/', 'https://www.linkedin.com/', url)

_SEARCH_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    "?keywords={kw}&location={loc}&start={start}"
)

# ── automatable-role taxonomy: category -> (keywords, pain, package) ───────────
# Ordered most-specific first; first match wins.
_ROLE_RULES: list[tuple[str, list[str], str, str]] = [
    ("booking", ["booking", "appointment", "reservation", "scheduling coordinator", "scheduler"],
     "answering the same WhatsApp questions, confirming bookings and chasing no-shows by hand",
     "WhatsApp Booking & Order Bot"),
    ("support", ["customer support", "customer service", "customer care", "support agent",
                 "call center", "call centre", "help desk", "helpdesk", "client relations"],
     "answering the same customer questions over and over across WhatsApp, email and chat",
     "AI Support Agent (EN/AR)"),
    ("finance", ["accountant", "accounts", "bookkeep", "book keep", "invoic", "billing",
                 "collections", "accounts payable", "accounts receivable"],
     "cutting invoices, reconciling numbers and chasing overdue payments by hand",
     "Invoice & Cash-Flow Automation"),
    ("data_entry", ["data entry", "data processor", "data processing", "typist", "encoder",
                    "data clerk", "file clerk", "documentation specialist", "records"],
     "keying the same data between systems and spreadsheets by hand all day",
     "Ops & Data Autopilot"),
    ("marketing", ["social media", "community manager", "content coordinator",
                   "digital marketing coordinator", "marketing assistant"],
     "posting, replying to DMs and compiling engagement reports manually",
     "Lead-to-CRM Autopilot"),
    ("sales_ops", ["sales admin", "sales coordinator", "sales support", "lead generation",
                   "telesales", "telemarketing", "crm"],
     "copying leads between forms, WhatsApp and the CRM and replying to them by hand",
     "Lead-to-CRM Autopilot"),
    ("admin", ["administrative assistant", "admin assistant", "office administrator",
               "office admin", "executive assistant", "personal assistant", "receptionist",
               "office coordinator", "back office", "back-office", "operations coordinator",
               "operations assistant", "clerk", "coordinator", "virtual assistant", "timekeeper"],
     "juggling scheduling, email, data entry and follow-ups that eat the whole day",
     "Ops & Data Autopilot"),
]

# staffing agencies (they hire on behalf of others — not the automation buyer)
_AGENCY_MARKERS = [
    "confidential", "recruitment", "recruiting", "staffing", "manpower", "employment services",
    "hr solutions", "hr consult", "talent", "michael page", "hays", "adecco", "randstad",
    "guildhall", "rtc-1", "robert half", "jobs for humanity", "career", "headhunt", "outsourc",
]
# large enterprises that run their own automation teams — wrong size for a freelancer
# (belt-and-suspenders: is_enterprise_by_size() is the durable catch-all via
# LinkedIn's own headcount field; this list is a fast pre-fetch shortcut)
_ENTERPRISE_MARKERS = [
    "saipem", "gems education", "nmdc", "azadea", "nextcare", "unilever", "nestle", "pepsi",
    "aramco", "adnoc", "emirates", "etisalat", "majid al futtaim", "chalhoub", "landmark group",
    "careem", "talabat", "noon", "aldar", "emaar", "damac", "siemens", "schneider", "accenture",
    "deloitte", "kpmg", "pwc", "ey ", "government", "ministry", "municipality", "authority",
    "kempinski", "radisson", "marriott", "hilton", "accor", "hyatt", "rotana", "intercontinental",
]
# NGOs / int'l orgs / government-adjacent — wrong ICP regardless of size (not a
# freelance-automation buyer; different budget process and buying behavior)
_NGO_MARKERS = [
    "reliefweb", "united nations", "unicef", "unhcr", "unrwa", "undp", "unfpa", "ocha",
    "world food programme", "wfp ", "red cross", "red crescent", "ifrc", "icrc",
    "world health organization", "who ", "embassy", "consulate", " ngo", "non-profit",
    "nonprofit", "foundation for", "humanitarian",
]

# "skip LOGOS": exclude software/tech companies — they build automation in-house
# or are direct competitors, not buyers. LinkedIn's own Industry taxonomy is the
# reliable signal; company-name keywords are a fallback when industry is unknown.
_SOFTWARE_INDUSTRIES = [
    "computer software", "software development", "information technology",
    "it services", "it consulting", "internet", "computer games", "saas",
    "computer & network security", "computer hardware", "computer networking",
    "web services", "information services", "technology, information and internet",
]
_SOFTWARE_NAME_MARKERS = [
    "software", "technologies", "technology", " tech ", "tech.", "digital agency",
    "web development", "app development", "saas", "informatics", "it services",
    "it solutions", "programming", "coding", "developers", "web design",
    "digital solutions", "cyber", "cloud services",
]


_DT_DD_RE = re.compile(r'<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>', re.DOTALL)


def _parse_about_fields(page_html: str) -> dict[str, str]:
    """Generic label -> value map from a LinkedIn company about page.

    LinkedIn's guest markup has no stable data-test-id for these fields (that
    was a wrong assumption from an earlier version of this module); the only
    reliable structure is plain <dt>Label</dt><dd>Value</dd> pairs. Labels are
    only in English when the page is fetched via www.linkedin.com with an
    English Accept-Language header — country subdomains (ae./lb./it....)
    localize the labels, so callers MUST normalize the URL first (see
    _normalize_company_url).
    """
    if not page_html:
        return {}
    fields: dict[str, str] = {}
    for label_html, value_html in _DT_DD_RE.findall(page_html):
        label = _clean(label_html).lower()
        if label and label not in fields:
            fields[label] = _clean(value_html)
    return fields


def extract_company_industry(page_html: str) -> str | None:
    """Extract the 'Industry' field from a LinkedIn company about page."""
    return _parse_about_fields(page_html).get("industry") or None


def extract_company_size(page_html: str) -> str | None:
    """Extract the 'Company size' field (e.g. '11-50 employees')."""
    return _parse_about_fields(page_html).get("company size") or None


_SIZE_UPPER_RE = re.compile(r'([\d,]+)\s*(?:employees)?\s*$')


def is_enterprise_by_size(size_text: str | None) -> bool:
    """True once LinkedIn's own headcount says >1,000 employees.

    Catches multinationals a name blocklist will never fully enumerate (e.g.
    Kempinski Hotels) without needing per-brand entries. Unknown size never
    excludes on its own — a small company with a blank profile is still a
    valid lead.
    """
    if not size_text:
        return False
    text = size_text.replace(",", "").lower()
    if "+" in text:
        return True  # "10001+ employees"
    numbers = re.findall(r'\d+', text)
    if not numbers:
        return False
    return int(numbers[-1]) > 1000


def is_software_company(name: str, industry: str | None = None) -> bool:
    """'Skip LOGOS': true for software/tech companies — they build or compete,
    not buy. Prefers the LinkedIn industry field; falls back to name keywords
    when industry is unknown."""
    if industry:
        industry_lower = industry.lower()
        if any(marker in industry_lower for marker in _SOFTWARE_INDUSTRIES):
            return True
        return False
    name_lower = f" {(name or '').lower()} "
    return any(marker in name_lower for marker in _SOFTWARE_NAME_MARKERS)


def classify_automatable_role(title: str) -> dict | None:
    """Map a job title to an automation category, pain line, and package."""
    t = (title or "").lower()
    if not t.strip():
        return None
    for category, keywords, pain, package in _ROLE_RULES:
        if any(kw in t for kw in keywords):
            return {"category": category, "pain": pain, "package": package}
    return None


def is_low_value_company(name: str, slug: str) -> bool:
    """True for anonymous listings, staffing agencies, big enterprises, and NGOs/int'l orgs."""
    blob = f" {name} {slug} ".lower()
    return any(m in blob for m in _AGENCY_MARKERS + _ENTERPRISE_MARKERS + _NGO_MARKERS)


# ── parsing ───────────────────────────────────────────────────────────────────

_CARD_SPLIT = re.compile(r'<li[ >]')
_TITLE_RE = re.compile(r'base-search-card__title[^>]*>\s*(.*?)\s*</h3>', re.DOTALL)
_COMPANY_RE = re.compile(r'hidden-nested-link[^>]*href="([^"]+/company/([^"?/]+)[^"]*)"[^>]*>\s*(.*?)\s*</a>', re.DOTALL)
_LOCATION_RE = re.compile(r'job-search-card__location[^>]*>\s*(.*?)\s*</span>', re.DOTALL)
_JOBURL_RE = re.compile(r'href="(https://[a-z]{0,3}\.?linkedin\.com/jobs/view/[^"]+)"')


def _clean(text: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or ""))).strip()


def parse_job_cards(page_html: str) -> list[dict]:
    """Parse LinkedIn jobs-guest HTML into job-card dicts."""
    if not page_html:
        return []
    cards = []
    # each job is one <li>; split on the list-item boundary so the job URL,
    # title, company and location for a card stay together
    for chunk in _CARD_SPLIT.split(page_html)[1:]:
        title_m = _TITLE_RE.search(chunk)
        company_m = _COMPANY_RE.search(chunk)
        if not title_m or not company_m:
            continue
        company_url = company_m.group(1).split("?")[0]
        slug = company_m.group(2)
        location = _clean(_LOCATION_RE.search(chunk).group(1)) if _LOCATION_RE.search(chunk) else ""
        job_m = _JOBURL_RE.search(chunk)
        cards.append({
            "title": _clean(title_m.group(1)),
            "company": _clean(company_m.group(3)),
            "company_slug": slug,
            "company_linkedin_url": company_url,
            "location": location,
            "country": location.split(",")[-1].strip() if location else "",
            "job_url": html.unescape(job_m.group(1)) if job_m else "",
        })
    return cards


_URL_IN_TEXT_RE = re.compile(r'https?://[^\s]+')
_REDIRECT_RE = re.compile(r'redir/redirect\?url=([^"&]+)')


def company_website_from_linkedin(page_html: str) -> str | None:
    """Extract the real company website from a LinkedIn company page.

    Prefers the visible URL text in the 'Website' field (e.g. the dd renders
    'http://www.acme.com External link for Acme') over decoding the wrapped
    redir/redirect href — simpler and avoids grabbing an unrelated redirect
    link elsewhere on the page.
    """
    if not page_html:
        return None
    from scrapers.email_finder import normalize_domain

    website_field = _parse_about_fields(page_html).get("website")
    if website_field:
        m = _URL_IN_TEXT_RE.search(website_field)
        if m:
            domain = normalize_domain(m.group(0))
            if domain:
                return domain

    # fallback: decode the wrapped redirect href (older/variant markup)
    m = _REDIRECT_RE.search(page_html)
    if not m:
        return None
    url = urllib.parse.unquote(urllib.parse.unquote(m.group(1)))
    url = url.replace("%2E", ".").replace("%2F", "/")
    domain = normalize_domain(url)
    return domain or None


# ── live orchestration ────────────────────────────────────────────────────────

async def _fetch_text(session: aiohttp.ClientSession, url: str, chrome: bool = False) -> str | None:
    try:
        headers = _CHROME_UA if chrome else _HEADERS
        async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                logger.debug("LinkedIn %s -> %d", url, resp.status)
                return None
            return await resp.text()
    except Exception as e:
        logger.debug("fetch failed %s: %s", url, e)
        return None


async def _fetch_via_curl(url: str, headers: dict[str, str]) -> str | None:
    """Shell out to curl.exe for the LinkedIn company-about page.

    Confirmed live 2026-07-10: LinkedIn's guest company page returns HTTP 999
    (its bot-block code) to aiohttp's TLS ClientHello fingerprint on ~every
    request, while curl.exe succeeds reliably on the identical URL — this is
    TLS/JA3-level bot detection that HTTP headers alone can't work around.
    """
    if not shutil.which("curl"):
        return None
    cmd = ["curl", "-s", "-L", "--max-time", "15"]
    for k, v in headers.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        if proc.returncode != 0 or not stdout:
            return None
        return stdout.decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("curl fallback failed %s: %s", url, e)
        return None


async def _fetch_company_page(session: aiohttp.ClientSession, url: str) -> str | None:
    """Fetch a LinkedIn company-about page, falling back to curl.exe when
    aiohttp gets bot-blocked (see _fetch_via_curl)."""
    page = await _fetch_text(session, url, chrome=True)
    if page:
        return page
    return await _fetch_via_curl(url, _CHROME_UA)


async def find_leads(
    keywords: list[str],
    locations: list[str],
    per_search: int = 25,
    delay: float = 1.5,
) -> list[dict]:
    """Discover automatable-role leads across keyword x location, deduped by company.

    Returns lead dicts WITHOUT email (email enrichment is a separate step via
    scrapers.email_finder so this stays testable and fast).
    """
    seen: set[str] = set()
    leads: list[dict] = []
    async with aiohttp.ClientSession() as session:
        for kw in keywords:
            for loc in locations:
                url = _SEARCH_URL.format(
                    kw=urllib.parse.quote(kw), loc=urllib.parse.quote(loc), start=0
                )
                page = await _fetch_text(session, url, chrome=False)
                for card in parse_job_cards(page or ""):
                    role = classify_automatable_role(card["title"])
                    if role is None:
                        continue
                    if is_low_value_company(card["company"], card["company_slug"]):
                        continue
                    if is_software_company(card["company"]):  # fast name-based pre-filter
                        continue
                    key = card["company_slug"].lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    website = None
                    industry = None
                    company_size = None
                    co_url = _normalize_company_url(card["company_linkedin_url"]) + "/"
                    co_page = await _fetch_company_page(session, co_url)
                    await asyncio.sleep(0.5)  # politeness between company-page fetches
                    if co_page:
                        website = company_website_from_linkedin(co_page)
                        industry = extract_company_industry(co_page)
                        company_size = extract_company_size(co_page)
                    if is_software_company(card["company"], industry=industry):
                        continue
                    if is_enterprise_by_size(company_size):
                        continue
                    leads.append({
                        "company": card["company"],
                        "website": website,
                        "industry": industry,
                        "company_size": company_size,
                        "role_title": card["title"],
                        "category": role["category"],
                        "pain": role["pain"],
                        "package": role["package"],
                        "location": card["location"],
                        "country": card["country"],
                        "city": card["location"].split(",")[0].strip() if card["location"] else "",
                        "job_url": card["job_url"],
                        "company_linkedin_url": card["company_linkedin_url"],
                    })
                if delay and page:
                    await asyncio.sleep(delay)
    return leads


# canonical search set for Gulf + Lebanon
DEFAULT_KEYWORDS = [
    "data entry", "administrative assistant", "customer support", "booking coordinator",
    "accountant", "social media", "personal assistant", "back office",
]
DEFAULT_LOCATIONS = [
    "United Arab Emirates", "Saudi Arabia", "Qatar", "Beirut, Lebanon",
]
