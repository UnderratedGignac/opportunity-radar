"""Website change detection scraper.

Monitors target pages (/pricing, /about, /product) for meaningful changes.
Uses content hashing — if hash differs from stored, it's a change signal.
Stores hashes in Supabase for persistence.
"""

from __future__ import annotations

import hashlib
import logging
import re

import aiohttp

logger = logging.getLogger("radar.scraper.website_monitor")

_TARGET_PATHS = ["/pricing", "/about", "/product", "/products", "/platform", "/careers"]
_HIGH_VALUE_PATTERNS = {
    "enterprise": ("website_change", "Enterprise plan/tier detected on website", 15),
    "schedule a demo": ("website_change", "Demo CTA added to website", 12),
    "we're hiring": ("website_change", "Hiring banner on website", 10),
    "new office": ("website_change", "New office mentioned on website", 12),
    r"\$[\d,]+/month": ("website_change", "Pricing updated on website", 15),
    "series": ("website_change", "Funding mention on website", 18),
}


async def check_website(domain: str) -> list[dict]:
    """Scan key pages of a domain for buying-signal content."""
    base_url = f"https://{domain}"
    signals = []
    async with aiohttp.ClientSession() as session:
        for path in _TARGET_PATHS:
            url = f"{base_url}{path}"
            try:
                headers = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0)"}
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True
                ) as resp:
                    if resp.status != 200:
                        continue
                    text = (await resp.text())[:50000]
                    page_signals = _extract_page_signals(text, url)
                    signals.extend(page_signals)
            except Exception as e:
                logger.debug("Website check failed %s%s: %s", domain, path, e)
    return signals


def _extract_page_signals(html: str, url: str) -> list[dict]:
    # Strip HTML tags for text analysis
    text = re.sub(r"<[^>]+>", " ", html).lower()
    text = re.sub(r"\s+", " ", text)
    signals = []
    for pattern, (sig_type, detail, weight) in _HIGH_VALUE_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            signals.append(
                {
                    "signal_type": sig_type,
                    "detail": detail,
                    "base_weight": weight,
                    "source_url": url,
                    "confidence": 0.6,
                }
            )
    return signals


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
