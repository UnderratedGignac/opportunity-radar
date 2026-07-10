"""Funding-event scraper — merged Google News / Crunchbase / TechCrunch / PRNewswire feeds.

Funding announcements are the highest-value buying-intent signal: fresh budget
plus pressure to grow. All four feeds are free RSS verified live 2026-07-08.
Company names and amounts are extracted from headlines; events are deduped by
normalized company name.

Supersedes scrapers/crunchbase.py (single-feed version).
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import aiohttp

logger = logging.getLogger("radar.scraper.funding_news")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0; eliehaddadh1@gmail.com)"}
_TIMEOUT = aiohttp.ClientTimeout(total=15)

# VC-fund raises, listicles, and roundups are not startup buying intent
_NOISE = re.compile(
    r"\bfunds?\b|\bunicorns\b|vc firm|venture firm|venture fund|biggest funding"
    r"|top \d+|\bthese startups\b|\blayoffs\b|\btracker\b",
    re.IGNORECASE,
)

_TITLE_PATTERN = re.compile(
    r"^(?P<company>.+?)\s+(?:has\s+|have\s+|is\s+)?"
    r"(?:rais(?:es?|ed|ing)|secur(?:es?|ed)|lands?|landed|clos(?:es?|ed)|nets?|banks?)\s+"
    r"(?P<cur>[$€£])\s?(?P<num>\d[\d.,]*)\s*(?P<mult>billion|million|[bmk])?\b",
    re.IGNORECASE,
)

_ROUND_PATTERN = re.compile(r"\b(pre-?seed|seed|series\s+[a-e]|growth)\s+(?:round|funding|financing)?", re.IGNORECASE)
_DESCRIPTOR_PATTERN = re.compile(r"^.*\bstartups?\s+", re.IGNORECASE)

# headlines like "After three exits, Eyal Azoulay raises ..." put narrative, not
# a company name, before the verb
_NARRATIVE_STARTERS = {
    "after", "before", "following", "fresh", "amid", "despite", "with",
    "as", "why", "how", "what", "when", "where", "inside", "meet",
    "exclusive", "breaking", "report", "this", "these",
}


def parse_funding_title(title: str) -> dict | None:
    """Extract {company, amount_millions, round_type} from a funding headline."""
    if not title or _NOISE.search(title):
        return None
    match = _TITLE_PATTERN.search(title)
    if not match:
        return None

    # appositive headlines: "Acme, a fintech startup, raises ..." — company is
    # the segment before the first comma
    company = match.group("company").split(",")[0]
    company = _DESCRIPTOR_PATTERN.sub("", company).strip(" ,.-–—")
    words = company.split()
    if not words or len(company) > 60 or len(words) > 5:
        return None
    if words[0].lower() in _NARRATIVE_STARTERS:
        return None

    try:
        amount = float(match.group("num").replace(",", ""))
    except ValueError:
        return None
    mult = (match.group("mult") or "").lower()
    if mult in ("billion", "b"):
        amount *= 1000
    elif mult == "k":
        amount /= 1000
    elif not mult and amount >= 10000:  # raw dollars, e.g. "$2,000,000"
        amount /= 1_000_000

    round_match = _ROUND_PATTERN.search(title)
    round_type = None
    if round_match:
        round_type = re.sub(r"\s+", " ", round_match.group(1).lower())
        # only trust a round mention that names an actual stage
        if round_type == "growth" and "growth round" not in title.lower():
            round_type = None

    return {"company": company, "amount_millions": amount, "round_type": round_type}


_SUFFIX_TOKENS = {"inc", "llc", "ltd", "corp", "co", "ai", "labs", "hq", "io", "technologies"}


def _normalize(name: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).split()
    while len(tokens) > 1 and tokens[-1] in _SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def _richness(event: dict) -> int:
    return sum(1 for k in ("amount_millions", "round_type", "published_at", "source_name") if event.get(k))


def _dedupe(events: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for event in events:
        key = _normalize(event.get("company", ""))
        if not key:
            continue
        if key not in best or _richness(event) > _richness(best[key]):
            best[key] = event
    return list(best.values())


def _parse_rss_items(xml_text: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.warning("RSS parse error: %s", e)
        return []
    for item in root.findall(".//item"):
        pub_date = None
        raw_date = item.findtext("pubDate")
        if raw_date:
            try:
                pub_date = parsedate_to_datetime(raw_date)
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pub_date = None
        items.append({
            "title": item.findtext("title") or "",
            "link": item.findtext("link") or "",
            "pub_date": pub_date,
            "source": (item.findtext("source") or "").strip() or None,
        })
    return items


def parse_feed(
    xml_text: str,
    source_name: str,
    confidence: float,
    days: int = 7,
    now: datetime | None = None,
) -> list[dict]:
    """Parse one RSS feed into deduped funding events within the recency window."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    events = []
    for item in _parse_rss_items(xml_text):
        if item["pub_date"] is not None and item["pub_date"] < cutoff:
            continue
        parsed = parse_funding_title(item["title"])
        if parsed is None:
            continue
        src = item["source"] or source_name
        detail = f"Raised ${parsed['amount_millions']:g}M"
        if parsed["round_type"]:
            detail += f" {parsed['round_type'].title()}"
        detail += f" ({src})"
        events.append({
            **parsed,
            "signal_type": "funding",
            "detail": detail,
            "source_url": item["link"],
            "source_name": src,
            "published_at": item["pub_date"].isoformat() if item["pub_date"] else None,
            "confidence": confidence,
        })
    return _dedupe(events)


# ── feeds ─────────────────────────────────────────────────────────────────────

def _google_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )


def _feeds(days: int) -> list[tuple[str, str, float]]:
    return [
        (_google_url(f'"raised" "Series A" when:{days}d'), "google_news", 0.8),
        (_google_url(f'"seed round" when:{days}d'), "google_news", 0.8),
        (_google_url(f'"Series B" when:{days}d'), "google_news", 0.8),
        ("https://news.crunchbase.com/feed/", "crunchbase_news", 0.8),
        ("https://techcrunch.com/category/venture/feed/", "techcrunch", 0.85),
        ("https://www.prnewswire.com/rss/news-releases-list.rss", "prnewswire", 0.7),
    ]


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                logger.debug("Feed returned %d: %s", resp.status, url)
                return None
            return await resp.text()
    except Exception as e:
        logger.debug("Feed fetch failed %s: %s", url, e)
        return None


async def fetch_funding_events(days: int = 7, limit: int = 100) -> list[dict]:
    """Deduped funding events from all feeds, newest window only."""
    try:
        async with aiohttp.ClientSession() as session:
            texts = await asyncio.gather(
                *[_fetch_text(session, url) for url, _, _ in _feeds(days)]
            )
    except Exception as e:
        logger.error("Funding feed gather failed: %s", e)
        return []
    events: list[dict] = []
    for text, (_, source_name, confidence) in zip(texts, _feeds(days)):
        if text:
            events.extend(parse_feed(text, source_name, confidence, days=days))
    return _dedupe(events)[:limit]


_NEGATIVE_PATTERN = re.compile(r"\blayoffs?\b|\blaying off\b|hiring freeze|shuts? down|winding down", re.IGNORECASE)


async def negative_signals(company_name: str, days: int = 90) -> list[dict]:
    """Layoffs / hiring-freeze news for a company — buying-window killers.

    Titles must both match a negative pattern AND name the company, to avoid
    penalizing companies that merely appear near sector-wide layoff stories.
    """
    if not company_name or not company_name.strip():
        return []
    url = _google_url(f'"{company_name}" (layoffs OR "hiring freeze") when:{days}d')
    try:
        async with aiohttp.ClientSession() as session:
            text = await _fetch_text(session, url)
    except Exception as e:
        logger.warning("Negative-news check failed for %s: %s", company_name, e)
        return []
    if not text:
        return []
    name_lower = company_name.lower()
    signals = []
    for item in _parse_rss_items(text)[:10]:
        title = item["title"]
        if name_lower in title.lower() and _NEGATIVE_PATTERN.search(title):
            signals.append({
                "signal_type": "news",
                "detail": title[:140],
                "source_url": item["link"],
                "confidence": 0.6,
                "negative": True,
            })
    return signals


async def company_news(company_name: str, days: int = 7) -> list[dict]:
    """Per-company Google News check — returns canonical signal dicts."""
    if not company_name or not company_name.strip():
        return []
    url = _google_url(f'"{company_name}" funding when:{days}d')
    try:
        async with aiohttp.ClientSession() as session:
            text = await _fetch_text(session, url)
    except Exception as e:
        logger.warning("Company news failed for %s: %s", company_name, e)
        return []
    if not text:
        return []
    signals = []
    for item in _parse_rss_items(text)[:5]:
        parsed = parse_funding_title(item["title"])
        if parsed:
            signals.append({
                "signal_type": "funding",
                "detail": f"Raised ${parsed['amount_millions']:g}M"
                + (f" {parsed['round_type'].title()}" if parsed["round_type"] else ""),
                "source_url": item["link"],
                "confidence": 0.75,
            })
        else:
            signals.append({
                "signal_type": "news",
                "detail": item["title"][:140],
                "source_url": item["link"],
                "confidence": 0.5,
            })
    return signals
