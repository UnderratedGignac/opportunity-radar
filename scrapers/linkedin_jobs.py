"""Job signal scraper — Indeed RSS (free, no API key needed).

Detects high-signal roles: SDR, AE, VP Sales, RevOps, Marketing, CS.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import aiohttp

logger = logging.getLogger("radar.scraper.jobs")

_HIGH_SIGNAL_ROLES = {
    "sdr": ("hiring", "sales development representative", 28),
    "sales development": ("hiring", "sales development", 28),
    "account executive": ("hiring", "account executive", 25),
    "vp sales": ("exec_change", "VP Sales hired", 35),
    "vp of sales": ("exec_change", "VP of Sales hired", 35),
    "chief revenue": ("exec_change", "CRO/Chief Revenue Officer hired", 35),
    "vp marketing": ("exec_change", "VP Marketing hired", 30),
    "cmo": ("exec_change", "CMO hired", 30),
    "revenue operations": ("hiring", "RevOps hire", 18),
    "marketing manager": ("hiring", "marketing manager hire", 22),
    "customer success": ("hiring", "customer success hire", 20),
}

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0)"}


async def scrape_jobs_for_company(company_name: str, limit: int = 20) -> list[dict]:
    """Return high-signal job postings for a company via Indeed RSS."""
    query = company_name.replace(" ", "+")
    url = f"https://www.indeed.com/rss?q={query}&sort=date&fromage=14"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return []
                text = await resp.text()
        return _parse_rss(text, company_name, limit)
    except Exception as e:
        logger.debug("Indeed RSS failed for %s: %s", company_name, e)
        return []


def _parse_rss(xml: str, company_name: str, limit: int) -> list[dict]:
    signals = []
    try:
        root = ET.fromstring(xml)
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").lower()
            link = item.findtext("link") or ""
            signal = _classify_job_title(title, link)
            if signal:
                signals.append({**signal, "company": company_name})
    except ET.ParseError:
        pass
    return signals


def _classify_job_title(title_lower: str, source_url: str) -> dict | None:
    for keyword, (sig_type, detail, weight) in _HIGH_SIGNAL_ROLES.items():
        if keyword in title_lower:
            return {
                "signal_type": sig_type,
                "detail": detail,
                "base_weight": weight,
                "source_url": source_url,
                "confidence": 0.85,
            }
    return None
