"""Real contact-email finder — scrapes a company's own website.

Guessed addresses (hello@, firstname.lastname@) bounce ~60% of the time and
hard bounces hurt sender reputation. This module instead extracts emails a
company actually publishes on its site, then MX-checks the domain so we only
send where mail can be delivered.

Flow: fetch homepage + a few likely contact pages, regex out real addresses,
drop junk (asset filenames, tracking DSNs, placeholders, off-domain badges),
rank personal > role inbox, and verify the domain accepts mail.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import smtplib
import subprocess

import aiohttp

logger = logging.getLogger("radar.scraper.email_finder")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0; eliehaddadh1@gmail.com)"}
_TIMEOUT = aiohttp.ClientTimeout(total=10)
# imprint/impressum and privacy/terms pages legally must carry a contact email
# in many jurisdictions, so they are the best source when the site hides it
_CONTACT_PATHS = [
    "", "/contact", "/contact-us", "/get-in-touch", "/about", "/about-us",
    "/company", "/team", "/our-team", "/people", "/imprint", "/impressum",
    "/legal", "/privacy", "/privacy-policy", "/terms",
]

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# addresses that are never a real human contact
_JUNK_LOCALPARTS = {"noreply", "no-reply", "donotreply", "example", "email", "user",
                    "name", "your", "sentry", "wixpress"}
_JUNK_DOMAINS = {"example.com", "domain.com", "sentry.io", "wix.com", "trustpilot.com",
                 "google.com", "gmail.com", "googlemail.com", "schema.org", "w3.org",
                 "sentry-next.wixpress.com"}
_ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".ico")

# ranking: lower rank sorts first
_PREFERRED_ROLES = ["hello", "contact", "info", "hi", "team", "sales", "partnerships"]
_DEPRIORITIZED_ROLES = ["support", "help", "careers", "jobs", "press", "media",
                        "legal", "privacy", "billing", "admin", "webmaster"]
_LAST_ROLES = ["noreply", "no-reply", "donotreply"]


def normalize_domain(url: str) -> str:
    if not url:
        return ""
    d = re.sub(r"^https?://", "", url.strip().lower())
    d = re.sub(r"^www\.", "", d)
    return d.split("/")[0].split("?")[0]


def _is_junk(email: str) -> bool:
    local, _, domain = email.lower().partition("@")
    if not domain or "." not in domain:
        return True
    if email.lower().endswith(_ASSET_EXT):
        return True
    if local in _JUNK_LOCALPARTS or domain in _JUNK_DOMAINS:
        return True
    if any(part.isdigit() and len(part) > 6 for part in local.split(".")):
        return True  # hashed/tracking locals like sentry keys
    return False


def deobfuscate(text: str) -> str:
    """Turn common anti-scrape spellings back into real addresses.

    Handles 'name [at] domain [dot] com', '(at)'/'{at}', spaced '@ . ', so the
    plain email regex can then match them.
    """
    # [at] (at) {at} " at " -> @
    text = re.sub(r"\s*[\[\({]\s*at\s*[\]\)}]\s*", "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+at\s+", "@", text, flags=re.IGNORECASE)
    # [dot] (dot) {dot} " dot " -> .
    text = re.sub(r"\s*[\[\({]\s*dot\s*[\]\)}]\s*", ".", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+dot\s+", ".", text, flags=re.IGNORECASE)
    # collapse spaces around a literal @ or . inside address-looking runs
    text = re.sub(r"\s*@\s*", "@", text)
    text = re.sub(r"(@[\w-]+)\s*\.\s*(\w)", r"\1.\2", text)
    return text


def extract_emails(page_html: str, base_domain: str) -> list[str]:
    """Real, on-domain emails published in the page HTML (incl. obfuscated)."""
    if not page_html:
        return []
    text = deobfuscate(html.unescape(page_html))
    base = normalize_domain(base_domain)
    found: list[str] = []
    seen: set[str] = set()
    for raw in _EMAIL_RE.findall(text):
        email = raw.lower().strip(".")
        if email in seen or _is_junk(email):
            continue
        domain = email.partition("@")[2]
        # keep addresses on the company's own domain (or a subdomain of it)
        if base and not (domain == base or domain.endswith("." + base)):
            continue
        seen.add(email)
        found.append(email)
    return found


def _rank_emails(emails: list[str], base_domain: str) -> list[str]:
    def key(email: str):
        local = email.partition("@")[0]
        if local in _LAST_ROLES:
            bucket = 4
        elif local in _DEPRIORITIZED_ROLES:
            bucket = 3
        elif local in _PREFERRED_ROLES:
            bucket = 1
        elif "." in local or (local.isalpha() and len(local) <= 12):
            bucket = 0  # looks like a person's name
        else:
            bucket = 2
        return (bucket, len(email))

    return sorted(dict.fromkeys(emails), key=key)


def _mx_records(domain: str) -> list[tuple[int, str]]:
    """(preference, host) MX records for a domain, via nslookup."""
    domain = normalize_domain(domain)
    if not domain:
        return []
    try:
        out = subprocess.run(
            ["nslookup", "-type=mx", domain],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        logger.debug("MX lookup failed for %s: %s", domain, e)
        return []
    records = []
    combined = out.stdout + out.stderr
    # Windows: "MX preference = 5, mail exchanger = host"
    for m in re.finditer(
        r"preference\s*=\s*(\d+)\s*,\s*mail exchanger\s*=\s*([A-Za-z0-9.\-]+)",
        combined, re.IGNORECASE,
    ):
        records.append((int(m.group(1)), m.group(2).rstrip(".")))
    # Fallback (Unix dig-style or preference-less output): host after "exchanger ="
    if not records:
        for m in re.finditer(r"mail exchanger\s*=\s*([A-Za-z0-9.\-]+)", combined, re.IGNORECASE):
            records.append((10, m.group(1).rstrip(".")))
    return sorted(records)


def domain_has_mx(domain: str) -> bool:
    """Does the domain publish MX records (i.e. can it receive mail)?"""
    return bool(_mx_records(domain))


def _mx_host(domain: str) -> str | None:
    records = _mx_records(domain)
    return records[0][1] if records else None


def verify_mailbox(email: str, timeout: int = 12) -> bool | None:
    """Best-effort SMTP RCPT probe: does this specific mailbox exist?

    Returns True (accepted), False (explicitly rejected — a dead mailbox like
    DigX's), or None (inconclusive: port 25 blocked, greylisted, or accept-all
    server). Callers should only REFUSE to send on an explicit False.
    """
    if not email or "@" not in email:
        return None
    domain = email.split("@")[-1]
    host = _mx_host(domain)
    if not host:
        return False
    try:
        with smtplib.SMTP(host, 25, timeout=timeout) as server:
            try:
                server.ehlo()
            except Exception:
                server.helo()
            server.mail("verify@opportunityradar.io")
            code, _ = server.rcpt(email)
            if code in (250, 251):
                return True
            if code in (550, 551, 553, 554):
                return False
            return None
    except Exception as e:
        logger.debug("Mailbox probe inconclusive for %s: %s", email, e)
        return None


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT, allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype:
                return None
            return await resp.text()
    except Exception as e:
        logger.debug("Fetch failed %s: %s", url, e)
        return None


async def find_email(domain: str, company_name: str | None = None) -> dict:
    """Scrape a company's site for a real contact email.

    Returns {email, all_emails, contact_url, mx_ok, source}. `email` is the
    best-ranked verified address or None; `source` is 'website' when an address
    was found, else 'contact_page' (a URL a human can use) or 'unreachable'.
    """
    base = normalize_domain(domain)
    empty = {"email": None, "all_emails": [], "contact_url": "", "mx_ok": False, "source": "unreachable"}
    if not base:
        return empty

    mx_ok = domain_has_mx(base)
    all_emails: list[str] = []
    contact_url = f"https://{base}"
    reached = False

    async with aiohttp.ClientSession() as session:
        for path in _CONTACT_PATHS:
            url = f"https://{base}{path}"
            page = await _fetch_text(session, url)
            if page is None:
                continue
            reached = True
            emails = extract_emails(page, base)
            if emails:
                all_emails.extend(e for e in emails if e not in all_emails)
                if path in ("/contact", "/contact-us", "/get-in-touch"):
                    contact_url = url
                # stop early once a real page yielded addresses
                break

    if not reached:
        return {**empty, "mx_ok": mx_ok}

    ranked = _rank_emails(all_emails, base)
    if ranked:
        return {
            "email": ranked[0],
            "all_emails": ranked,
            "contact_url": contact_url,
            "mx_ok": mx_ok,
            "source": "website",
        }
    return {
        "email": None,
        "all_emails": [],
        "contact_url": contact_url,
        "mx_ok": mx_ok,
        "source": "contact_page",
    }
