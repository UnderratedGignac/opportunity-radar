"""Signal Collection Agent.

Scans free public sources for buying-intent signals at target companies.

Sources (all free, no API keys required):
  1. Google News RSS       — press releases, exec changes, funding announcements
  2. ATS job boards        — Greenhouse/Lever/Ashby public APIs, GTM hiring signals
  3. Hacker News           — company mentions
  4. Website monitor       — pricing/product page changes
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import aiohttp

from agents.base_agent import BaseAgent
from llm.claude_router import ClaudeRouter
from models.signal import Signal, SignalType
from scrapers.job_boards import scan_company_jobs
from scrapers.website_monitor import check_website

logger = logging.getLogger("radar.agent.signal_collection")

_EXTRACTION_SYSTEM = (
    "You are a business intelligence extraction AI. "
    "Extract structured buying-intent signals from raw text. "
    "Return ONLY valid JSON. Never invent signals not present in the text."
)

_EXTRACTION_PROMPT = """Given the following raw text from a public source, extract all business
signals indicating growth, executive changes, funding, technology adoption, or hiring patterns.

Source URL: {url}
Source Type: {source_type}
Raw Text (first 3000 chars): {text}

Return JSON:
{{
  "company_name": "string or null",
  "signals": [
    {{
      "type": "funding|hiring|exec_change|tech_change|website_change|news",
      "detail": "concise description under 20 words",
      "confidence": 0.0-1.0
    }}
  ]
}}

Only extract signals explicitly present. If none found, return {{"signals": []}}."""

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0)"}


class SignalCollectionAgent(BaseAgent[list[str], list[Signal]]):
    """Collect signals for a list of company domains using free sources only."""

    name = "signal_collection"

    def __init__(self, llm: ClaudeRouter | None = None, **_kwargs) -> None:
        super().__init__()
        self._llm = llm or ClaudeRouter()

    async def run(self, domains: list[str]) -> list[Signal]:
        self._log_start(f"{len(domains)} domains")
        tasks = [self._collect_for_domain(d) for d in domains]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        signals: list[Signal] = []
        for r in results:
            if isinstance(r, list):
                signals.extend(r)
            else:
                logger.warning("Signal collection error: %s", r)
        self._log_done(f"{len(signals)} signals collected")
        return signals

    async def _collect_for_domain(self, domain: str) -> list[Signal]:
        signals: list[Signal] = []
        tasks = [
            self._scrape_google_news(domain),
            self._scrape_jobs(domain),
            self._scrape_hackernews(domain),
            self._scrape_acquisitions(domain),
            self._scrape_prnewswire(domain),
            self._scrape_website(domain),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                signals.extend(r)
        return signals

    async def _scrape_website(self, domain: str) -> list[Signal]:
        try:
            items = await check_website(domain)
            signals = []
            for item in items:
                try:
                    sig_type = SignalType(item.get("signal_type", "website_change"))
                except ValueError:
                    sig_type = SignalType.WEBSITE_CHANGE
                signals.append(Signal(
                    company_domain=domain,
                    signal_type=sig_type,
                    detail=item.get("detail", ""),
                    source_url=item.get("source_url", f"https://{domain}"),
                    source_type="website",
                    confidence=float(item.get("confidence", 0.6)),
                ))
            return signals
        except Exception as e:
            logger.warning("Website monitor failed for %s: %s", domain, e)
            return []

    async def _scrape_hackernews(self, domain: str) -> list[Signal]:
        company_name = domain.split(".")[0].replace("-", " ").title()
        encoded = urllib.parse.quote(company_name)
        url = f"https://hn.algolia.com/api/v1/search?query={encoded}&tags=story&hitsPerPage=5"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
            signals: list[Signal] = []
            for hit in (data.get("hits") or [])[:5]:
                text = (hit.get("title") or "") + " " + (hit.get("url") or "")
                extracted = await self._extract_signals(text, hit.get("url") or url, "hackernews", domain)
                signals.extend(extracted)
            return signals
        except Exception as e:
            logger.warning("HackerNews scrape failed for %s: %s", domain, e)
            return []

    async def _scrape_acquisitions(self, domain: str) -> list[Signal]:
        company_name = domain.split(".")[0].replace("-", " ").title()
        query = urllib.parse.quote(
            f'"{company_name}" (acquired OR acquires OR merger OR IPO OR "went public" OR "strategic investment")'
        )
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return []
                    xml_text = await resp.text()
            items = _parse_rss(xml_text)
            signals: list[Signal] = []
            for item in items[:3]:
                text = f"{item['title']} {item['description']}"
                extracted = await self._extract_signals(text, item["link"], "news", domain)
                signals.extend(extracted)
            return signals
        except Exception as e:
            logger.warning("Acquisitions scrape failed for %s: %s", domain, e)
            return []

    async def _scrape_prnewswire(self, domain: str) -> list[Signal]:
        company_name = domain.split(".")[0].replace("-", " ").title()
        query = urllib.parse.quote(
            f'"{company_name}" site:businesswire.com OR site:prnewswire.com'
        )
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return []
                    xml_text = await resp.text()
            items = _parse_rss(xml_text)
            signals: list[Signal] = []
            for item in items[:3]:
                text = f"{item['title']} {item['description']}"
                extracted = await self._extract_signals(text, item["link"], "press_release", domain)
                signals.extend(extracted)
            return signals
        except Exception as e:
            logger.warning("PR Newswire scrape failed for %s: %s", domain, e)
            return []

    # ── Google News RSS (free, no key) ────────────────────────────────────────

    async def _scrape_google_news(self, domain: str) -> list[Signal]:
        company_name = domain.split(".")[0].replace("-", " ").title()
        query = urllib.parse.quote(
            f'"{company_name}" (funding OR raises OR "VP Sales" OR hired OR acquires OR launches)'
        )
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        return []
                    xml_text = await resp.text()
            items = _parse_rss(xml_text)
            signals: list[Signal] = []
            for item in items[:5]:
                text = f"{item['title']} {item['description']}"
                extracted = await self._extract_signals(text, item["link"], "news", domain)
                signals.extend(extracted)
            return signals
        except Exception as e:
            logger.warning("Google News scrape failed for %s: %s", domain, e)
            return []

    # ── ATS job boards (Greenhouse/Lever/Ashby public APIs, free, no key) ─────

    async def _scrape_jobs(self, domain: str) -> list[Signal]:
        company_name = domain.split(".")[0].replace("-", " ").title()
        try:
            items = await scan_company_jobs(company_name, domain, recent_days=30)
        except Exception as e:
            logger.debug("Job board scan skipped for %s: %s", domain, e)
            return []
        signals: list[Signal] = []
        for item in items:
            try:
                sig_type = SignalType(item.get("signal_type", "hiring"))
            except ValueError:
                sig_type = SignalType.HIRING
            signals.append(Signal(
                company_domain=domain,
                signal_type=sig_type,
                detail=item.get("detail", ""),
                source_url=item.get("source_url", f"https://{domain}"),
                source_type="job_board",
                confidence=float(item.get("confidence", 0.85)),
            ))
        return signals

    # ── LLM extraction ────────────────────────────────────────────────────────

    async def _extract_signals(
        self, text: str, url: str, source_type: str, domain: str
    ) -> list[Signal]:
        if not text.strip():
            return []
        prompt = _EXTRACTION_PROMPT.format(url=url, source_type=source_type, text=text[:3000])
        result = await self._llm.extract(prompt, _EXTRACTION_SYSTEM)
        # Fall back to keyword extraction if LLM unavailable
        raw = result.get("signals") or _keyword_extract(text)
        signals = []
        for s in raw:
            try:
                sig_type = SignalType(s.get("type", "news"))
            except ValueError:
                sig_type = SignalType.NEWS
            signals.append(
                Signal(
                    company_domain=domain,
                    signal_type=sig_type,
                    detail=s.get("detail", ""),
                    source_url=url,
                    source_type=source_type,
                    confidence=float(s.get("confidence", 0.5)),
                )
            )
        return signals


_KEYWORD_RULES: list[tuple[list[str], str, str, float]] = [
    (["series a", "series b", "series c", "seed round", "raises $", "raised $", "funding round"], "funding", "Funding event detected", 0.7),
    (["vp of sales", "vp sales", "chief revenue", "cro ", "cmo ", "vp marketing", "head of sales"], "exec_change", "Executive hire detected", 0.75),
    (["sdr", "sales development", "account executive", "revenue operations", "revops"], "hiring", "Sales role hiring", 0.7),
    (["launches", "new product", "new platform", "announces", "integrates with", "powered by ai"], "tech_change", "Product/tech change detected", 0.6),
    (["pricing", "new pricing", "price increase", "enterprise plan"], "website_change", "Pricing change detected", 0.65),
]


def _keyword_extract(text: str) -> list[dict]:
    lower = text.lower()
    seen: set[str] = set()
    signals = []
    for keywords, sig_type, detail, confidence in _KEYWORD_RULES:
        if sig_type in seen:
            continue
        if any(kw in lower for kw in keywords):
            seen.add(sig_type)
            signals.append({"type": sig_type, "detail": detail, "confidence": confidence})
    return signals


def _parse_rss(xml_text: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item"):
            items.append({
                "title": item.findtext("title") or "",
                "link": item.findtext("link") or "",
                "description": item.findtext("description") or "",
            })
    except ET.ParseError:
        pass
    return items
