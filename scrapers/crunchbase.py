"""Crunchbase funding signal scraper.

Uses the free Crunchbase RSS feed + news search as primary.
No API key required for basic operation.
Upgrade to Crunchbase Basic API ($29/mo) for structured data.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger("radar.scraper.crunchbase")

_RSS_URL = "https://news.crunchbase.com/feed/"
_FUNDING_PATTERN = re.compile(
    r"(raised?|secured?|closed?|announced?)\s+\$?([\d,]+(?:\.\d+)?)\s*(million|M|billion|B)?",
    re.IGNORECASE,
)
_ROUND_PATTERN = re.compile(
    r"(pre-?seed|seed|series\s+[a-e]|growth|late.stage)\s+(round|funding)?",
    re.IGNORECASE,
)


async def fetch_recent_funding(limit: int = 50) -> list[dict]:
    """Fetch recent funding events from Crunchbase RSS."""
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0)"}
            async with session.get(_RSS_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning("Crunchbase RSS returned %d", resp.status)
                    return []
                text = await resp.text()
                return _parse_rss(text, limit)
    except Exception as e:
        logger.error("Crunchbase fetch failed: %s", e)
        return []


def _parse_rss(xml: str, limit: int) -> list[dict]:
    import xml.etree.ElementTree as ET
    events = []
    try:
        root = ET.fromstring(xml)
        items = root.findall(".//item")[:limit]
        for item in items:
            title = item.findtext("title", "")
            description = item.findtext("description", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            text = f"{title} {description}"

            funding_match = _FUNDING_PATTERN.search(text)
            round_match = _ROUND_PATTERN.search(text)

            if not funding_match:
                continue

            amount_raw = funding_match.group(2).replace(",", "")
            multiplier_str = (funding_match.group(3) or "").lower()
            try:
                amount = float(amount_raw)
                if multiplier_str in ("billion", "b"):
                    amount *= 1000
            except ValueError:
                amount = 0

            events.append(
                {
                    "title": title,
                    "link": link,
                    "pub_date": pub_date,
                    "amount_millions": amount,
                    "round_type": round_match.group(1) if round_match else "unknown",
                    "signal_detail": _build_detail(title, amount, round_match),
                }
            )
    except ET.ParseError as e:
        logger.warning("RSS parse error: %s", e)
    return events


def _build_detail(title: str, amount: float, round_match) -> str:
    round_str = round_match.group(0).strip() if round_match else "round"
    if amount >= 1:
        return f"Raised ${amount:.0f}M {round_str}"
    return f"Raised funding ({round_str})"
