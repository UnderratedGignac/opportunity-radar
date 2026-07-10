"""SEC EDGAR Form D funding-signal scraper.

Form D is the legally-required filing when a US company raises an exempt
offering (Reg D). Free, no API key. Pipeline:

  1. Full-text search index (efts.sec.gov) for recent Form D filings.
  2. Noise filter: most filers are pooled investment funds, not startups —
     drop Investment Company Act 3(c) exclusions and fund-patterned names.
  3. Optional detail fetch of primary_doc.xml for offering amounts.

SEC requires a real User-Agent with contact info (403 otherwise) and asks
for <=10 req/s; detail-fetch concurrency is capped at 5.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import aiohttp

logger = logging.getLogger("radar.scraper.sec_edgar")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0; eliehaddadh1@gmail.com)"}
_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_MAX_PAGES = 25
_DETAIL_CONCURRENCY = 5

# 'Company Name  (CIK 0001234567)' -> name + cik
_DISPLAY_NAME_RE = re.compile(r"^(?P<name>.*?)\s*\(CIK\s+(?P<cik>\d+)\)\s*$")

# Fund-style names: keyword optionally followed by a roman/arabic series
# number and an entity suffix at the END of the name.
_FUND_NAME_RE = re.compile(
    r"\b(fund|capital|partners|holdings|opportunit\w*|ventures?|equit\w*|acquisitions?|spv)s?\b"
    r"[ ,.]*([ivxlcdm]+|\d+)?[-,.]?\s*(l\.?\s?p\.?|llc|l\.l\.c\.?|ltd\.?)?\.?\s*$",
    re.IGNORECASE,
)
# SPV platforms ('X, a Series of Y LLC') and wrappers like 'OurCrowd (Investment in ...)'
_SPV_RE = re.compile(r"\ba\s+series\s+of\b|\(invest", re.IGNORECASE)

# Form D industryGroupType values that mean the filer is itself a fund
_POOLED_INDUSTRY = {"Pooled Investment Fund", "Investing"}


def is_pooled_fund(hit: dict) -> bool:
    """True if a raw search hit looks like a pooled investment fund / SPV.

    Primary signal: Investment Company Act 3(c) exclusion items (3C, 3C.1,
    3C.5, 3C.7, ...) — only pooled funds claim these. Secondary: fund-style
    entity names.
    """
    src = hit.get("_source", hit)
    items = src.get("items") or []
    if any(str(i).upper().replace(" ", "").startswith("3C") for i in items):
        return True
    names = src.get("display_names") or []
    name = names[0] if names else ""
    m = _DISPLAY_NAME_RE.match(name)
    if m:
        name = m.group("name")
    return bool(_FUND_NAME_RE.search(name) or _SPV_RE.search(name))


def parse_search_hits(payload: dict) -> list[dict]:
    """Convert a raw efts search payload into event dicts. No filtering."""
    events: list[dict] = []
    hits = (payload.get("hits") or {}).get("hits") or []
    for hit in hits:
        try:
            src = hit.get("_source") or {}
            display = (src.get("display_names") or [""])[0]
            m = _DISPLAY_NAME_RE.match(display)
            if m:
                company = m.group("name")
                cik = int(m.group("cik"))
            else:
                company = display.strip()
                ciks = src.get("ciks") or ["0"]
                cik = int(ciks[0])
            adsh = src.get("adsh") or ""
            adsh_nodash = adsh.replace("-", "")
            locations = src.get("biz_locations") or []
            filed_at = src.get("file_date", "")
            events.append(
                {
                    "company": company,
                    "cik": cik,
                    "amount_millions": None,
                    "signal_type": "funding",
                    "detail": "Filed SEC Form D (exempt offering)",
                    "source_url": (
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{cik}/{adsh_nodash}/{adsh}-index.htm"
                    ),
                    "filed_at": filed_at,
                    "published_at": filed_at,
                    "location": locations[0] if locations else "",
                    "confidence": 0.85,
                    "file_type": src.get("file_type", ""),
                    "adsh": adsh,
                }
            )
        except Exception as e:
            logger.debug("Skipping malformed hit: %s", e)
    return events


def _filter_hits(hits: list[dict]) -> list[dict]:
    """Keep only new Form D filings (no D/A amendments) from operating companies."""
    return [
        h
        for h in hits
        if (h.get("_source") or {}).get("file_type") == "D" and not is_pooled_fund(h)
    ]


def _parse_primary_doc(xml_text: str) -> dict:
    """Extract issuer + offering amounts from a Form D primary_doc.xml."""
    root = ET.fromstring(xml_text)

    def _amount(tag: str) -> float | None:
        raw = root.findtext(f".//offeringSalesAmounts/{tag}")
        if raw is None:
            return None
        try:
            return float(raw.strip())
        except ValueError:  # 'Indefinite'
            return None

    return {
        "entity_name": (root.findtext(".//primaryIssuer/entityName") or "").strip(),
        "industry_group": (root.findtext(".//industryGroup/industryGroupType") or "").strip(),
        "total_offering_amount": _amount("totalOfferingAmount"),
        "total_amount_sold": _amount("totalAmountSold"),
    }


def _fmt_millions(millions: float) -> str:
    return "$" + f"{millions:.1f}".rstrip("0").rstrip(".") + "M"


def _build_detail(
    total_sold: float | None, total_offering: float | None
) -> tuple[float | None, str]:
    """(amount_millions, detail string) from dollar amounts."""
    if total_sold and total_sold > 0:
        millions = total_sold / 1_000_000
        return millions, f"Filed SEC Form D — raised {_fmt_millions(millions)}"
    if total_offering and total_offering > 0:
        millions = total_offering / 1_000_000
        return millions, f"Filed SEC Form D — offering up to {_fmt_millions(millions)}"
    return None, "Filed SEC Form D (exempt offering)"


async def fetch_form_d_filings(
    days: int = 7, limit: int = 100, detail_limit: int = 20
) -> list[dict]:
    """Recent Form D raises by operating companies (funds filtered out).

    The first `detail_limit` events are enriched with offering amounts from
    primary_doc.xml; enriched events whose industry group marks them as a
    pooled fund are dropped.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    events: list[dict] = []
    try:
        async with aiohttp.ClientSession(headers=_HEADERS, timeout=_TIMEOUT) as session:
            offset = 0
            for _ in range(_MAX_PAGES):
                params = {
                    "q": "",
                    "forms": "D",
                    "dateRange": "custom",
                    "startdt": start.isoformat(),
                    "enddt": end.isoformat(),
                    "from": offset,
                }
                async with session.get(_SEARCH_URL, params=params) as resp:
                    if resp.status != 200:
                        logger.warning("EDGAR search returned %d", resp.status)
                        break
                    payload = await resp.json(content_type=None)
                hits = (payload.get("hits") or {}).get("hits") or []
                if not hits:
                    break
                events.extend(parse_search_hits({"hits": {"hits": _filter_hits(hits)}}))
                offset += len(hits)
                total = ((payload.get("hits") or {}).get("total") or {}).get("value", 0)
                if len(events) >= limit or offset >= total:
                    break
            events = events[:limit]
            if detail_limit > 0 and events:
                events = await _enrich_with_details(session, events, detail_limit)
    except Exception as e:
        logger.error("EDGAR Form D fetch failed: %s", e)
        return []
    logger.info("EDGAR Form D: %d operating-company raises", len(events))
    return events


async def _enrich_with_details(
    session: aiohttp.ClientSession, events: list[dict], detail_limit: int
) -> list[dict]:
    sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)

    async def enrich(event: dict) -> dict | None:
        url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{event['cik']}/{event['adsh'].replace('-', '')}/primary_doc.xml"
        )
        try:
            async with sem:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        logger.debug("Detail fetch %s -> %d", url, resp.status)
                        return event
                    text = await resp.text()
            doc = _parse_primary_doc(text)
            if doc["industry_group"] in _POOLED_INDUSTRY:
                return None  # fund that slipped past list-level filters
            if doc["entity_name"]:
                event["company"] = doc["entity_name"]
            amount, detail = _build_detail(
                doc["total_amount_sold"], doc["total_offering_amount"]
            )
            event["amount_millions"] = amount
            event["detail"] = detail
            if doc["industry_group"]:
                event["industry_group"] = doc["industry_group"]
        except Exception as e:
            logger.debug("Detail enrichment failed for %s: %s", event.get("company"), e)
        return event

    head = await asyncio.gather(*(enrich(e) for e in events[:detail_limit]))
    return [e for e in head if e is not None] + events[detail_limit:]
