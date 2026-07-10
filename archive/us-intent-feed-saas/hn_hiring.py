"""HN 'Ask HN: Who is hiring' scraper — Algolia API (free, no auth, ~10k req/hr).

Discovers the current monthly thread, pulls the full item tree, and parses
top-level job posts. First lines are conventionally pipe-delimited but field
order varies ('Location | Company | Role' vs 'Company | Role | Location'),
so parsing is heuristic and confidence is set accordingly (0.6-0.8).
"""

from __future__ import annotations

import html
import logging
import re

import aiohttp

logger = logging.getLogger("radar.scraper.hn_hiring")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0; eliehaddadh1@gmail.com)"}

_SEARCH_URL = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?query=%22who%20is%20hiring%22&tags=story,author_whoishiring&hitsPerPage=5"
)
_ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"
_FALLBACK_THREAD_ID = 48747976  # July 2026, in case discovery fails

_ROLE_KEYWORDS = re.compile(
    r"\b(?:engineer|developer|programmer|designer|scientist|researcher|architect"
    r"|devops|sre|manager|director|lead|founder|executive|analyst|recruiter"
    r"|intern|marketer|head of|vp|cto|ceo|coo|sales|growth|product)s?\b",
    re.I,
)
_GTM_RE = re.compile(r"\b(sales|account executive|growth|marketing|revenue|partnerships)\b", re.I)
_FUNDING_RES = [
    re.compile(r"\bseries\s+([a-e])\b", re.I),
    re.compile(r"\b(seed)\b", re.I),
    re.compile(r"\b(bootstrapped)\b", re.I),
    re.compile(r"\b(profitable)\b", re.I),
]
_COMMITMENT_RE = re.compile(r"\b(full[- ]?time|part[- ]?time|contract|internship|onsite|hybrid)\b", re.I)
_SALARY_RE = re.compile(r"[$€£]|\b\d{2,3}k\b|\bequity\b|\bbenefits\b|\bsalary\b", re.I)
_CITY_STATE_RE = re.compile(r"\b[A-Z][A-Za-z .'-]*,\s*[A-Z]{2}\b")
_KNOWN_CITIES_RE = re.compile(
    r"\b(nyc|sf|san francisco|new york|london|berlin|paris|amsterdam|boston"
    r"|austin|seattle|denver|chicago|toronto|vancouver|stockholm|dublin|tel aviv)\b",
    re.I,
)
# e.g. "WireScreen (Series A)" or "Pango (YC S26)" — funding info, not part of the name
_COMPANY_SUFFIX_RE = re.compile(r"\s*\(\s*(series\s+[a-e]|seed|yc\s+[sw]\d{2})[^)]*\)\s*$", re.I)


def _strip_html(text_html: str) -> str:
    """HTML -> plain text: <p> becomes newline, tags dropped, entities unescaped."""
    text = text_html.replace("<p>", "\n")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n"))


def _is_location(seg: str) -> bool:
    return bool(_CITY_STATE_RE.search(seg) or _KNOWN_CITIES_RE.search(seg))


def _split_roles(seg: str) -> list[str]:
    parts = re.split(r",| & | and | / ", seg)
    return [p.strip() for p in parts if p.strip()]


def parse_post(text_html: str) -> dict | None:
    """Parse one top-level 'Who is hiring' comment. None if unparseable."""
    if not text_html:
        return None
    plain = _strip_html(text_html)
    first_line = plain.split("\n", 1)[0]
    segments = [s.strip(" -–|") for s in first_line.split("|") if s.strip(" -–|")]
    if len(segments) < 2:
        return None

    company = None
    company_idx = -1
    location = None
    roles: list[str] = []
    for i, seg in enumerate(segments):
        low = seg.lower()
        is_remote_seg = "remote" in low
        is_role_seg = bool(_ROLE_KEYWORDS.search(seg))
        is_loc_seg = _is_location(seg)
        if is_role_seg and not _SALARY_RE.search(seg):
            roles.extend(_split_roles(seg))
        if location is None and is_loc_seg and not is_role_seg:
            location = seg
        if company is None and not (
            is_loc_seg
            or is_remote_seg
            or is_role_seg
            or _COMMITMENT_RE.search(seg)
            or _SALARY_RE.search(seg)
            or "http" in low
        ):
            company = _COMPANY_SUFFIX_RE.sub("", seg).strip()
            company_idx = i
    if not company:
        return None

    remote = "remote" in first_line.lower()
    funding_stage = None
    for rx in _FUNDING_RES:
        m = rx.search(plain)
        if m:
            funding_stage = m.group(0).lower() if m.lastindex is None else (
                f"series {m.group(1).lower()}" if rx is _FUNDING_RES[0] else m.group(1).lower()
            )
            break
    has_gtm_roles = bool(_GTM_RE.search(" ".join(roles)) or _GTM_RE.search(plain))
    snippet = re.sub(r"\s+", " ", plain).strip()[:200]

    confidence = 0.6
    if roles:
        confidence += 0.1
    if company_idx == 0:  # conventional company-first format — least ambiguous
        confidence += 0.1

    return {
        "company": company,
        "roles": roles,
        "location": location,
        "remote": remote,
        "funding_stage": funding_stage,
        "has_gtm_roles": has_gtm_roles,
        "snippet": snippet,
        "confidence": round(confidence, 2),
    }


def _pick_thread_id(search_json: dict) -> int | None:
    """Newest 'Who is hiring' story id — skips 'wants to be hired'/'freelancer' siblings."""
    for hit in search_json.get("hits", []):
        title = (hit.get("title") or "").lower()
        if "who is hiring" in title and "wants to be hired" not in title and "freelancer" not in title:
            try:
                return int(hit["objectID"])
            except (KeyError, ValueError, TypeError):
                continue
    return None


def _extract_signals(item_json: dict, limit: int = 500) -> list[dict]:
    """Top-level children only; entries with text=null are dead/flagged — skip."""
    signals: list[dict] = []
    for child in item_json.get("children") or []:
        if len(signals) >= limit:
            break
        if not child.get("text"):
            continue
        parsed = parse_post(child["text"])
        if parsed is None:
            continue
        roles = parsed["roles"]
        gtm_role = next((r for r in roles if _GTM_RE.search(r)), None)
        named = gtm_role or (roles[0] if roles else None)
        if named:
            n = len(roles)
            detail = f"Hiring {n} role{'s' if n != 1 else ''} incl. {named} (HN Who is Hiring)"
        else:
            detail = f"{parsed['company']} is hiring (HN Who is Hiring)"
        signals.append(
            {
                **parsed,
                "signal_type": "hiring",
                "detail": detail,
                "source_url": f"https://news.ycombinator.com/item?id={child.get('id')}",
                "base_weight": 25 if parsed["has_gtm_roles"] else 15,
                "published_at": child.get("created_at"),
            }
        )
    return signals


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict | None:
    async with session.get(url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        if resp.status != 200:
            logger.warning("HN Algolia %s -> HTTP %s", url, resp.status)
            return None
        return await resp.json()


async def fetch_hiring_posts(limit: int = 500) -> list[dict]:
    """Job-post signals from the current monthly 'Who is hiring' thread."""
    try:
        async with aiohttp.ClientSession() as session:
            thread_id = None
            search_json = await _get_json(session, _SEARCH_URL)
            if search_json:
                thread_id = _pick_thread_id(search_json)
            if thread_id is None:
                thread_id = _FALLBACK_THREAD_ID
                logger.info("HN thread discovery failed, using fallback id %s", thread_id)
            item_json = await _get_json(session, _ITEM_URL.format(id=thread_id))
        if not item_json:
            return []
        return _extract_signals(item_json, limit)
    except Exception as e:
        logger.warning("HN who-is-hiring fetch failed: %s", e)
        return []
