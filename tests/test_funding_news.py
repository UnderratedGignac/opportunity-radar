"""Tests for scrapers/funding_news.py — merged funding-event feed.

All tests run OFFLINE. Fixtures under tests/fixtures/funding_news_* are real
payloads captured 2026-07-08 from Google News RSS, TechCrunch venture RSS,
Crunchbase News RSS, and PRNewswire RSS.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.funding_news import (
    _dedupe,
    _normalize,
    company_news,
    parse_feed,
    parse_funding_title,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- parse_funding_title

@pytest.mark.parametrize(
    "title,company,amount,round_type",
    [
        ("Jota raises $30M Series A at $185M valuation - LatamList", "Jota", 30.0, "series a"),
        ("Aligned raises $60 million Series B to streamline messy B2B sales processes - CTech",
         "Aligned", 60.0, "series b"),
        # first amount after the verb wins, not the valuation
        ("Venice AI raises $65 million Series A at $1 billion equity valuation led by Dragonfly - The Block",
         "Venice AI", 65.0, "series a"),
        ("Quantifind has secured $200 million in a funding round led by Summit Partners. - N2K CyberWire",
         "Quantifind", 200.0, None),
        ("Patronus AI lands $50M to build 'digital worlds' that stress-test AI agents",
         "Patronus AI", 50.0, None),
        # leading descriptor stripped
        ("AI law startup Norm raises $120M, hits unicorn valuation", "Norm", 120.0, None),
        # euro amounts
        ("Telum Therapeutics raises €18 million to advance treatments", "Telum Therapeutics", 18.0, None),
        ("Oratomic Raises $300 Million Series A - The Quantum Insider", "Oratomic", 300.0, "series a"),
    ],
)
def test_parse_funding_title_positives(title, company, amount, round_type):
    parsed = parse_funding_title(title)
    assert parsed is not None, title
    assert parsed["company"] == company
    assert parsed["amount_millions"] == amount
    assert parsed["round_type"] == round_type


@pytest.mark.parametrize(
    "title",
    [
        # VC fund raises are noise, not startup buying intent
        "VC firm Chemistry is raising $500M for its second fund",
        "Seedcamp raises $320M for its new fund to expand its US footprint",
        "OpenAI, Anthropic backer MGX raises one of the biggest AI funds ever as it closes at $49 billion - CNBC",
        # listicles / roundups / no raise verb
        "Almost 90 new unicorns have been minted so far this year — here they are - TechCrunch",
        "CoreWeave - 2026 Funding Rounds & List of Investors - Tracxn",
        "The Week’s 10 Biggest Funding Rounds: AI, Energy And Biotech Lead The Way",
        "Crunchbase Data: Global Startup Investment Hit Record $510B In H1 2026",
        "What is Bending Spoons? The little-known AOL and Vimeo owner that’s now public",
        "",
        # narrative prefix captured as "company" — commas / long phrases are not company names
        "After three exits, Eyal Azoulay raises $20M seed for his next venture - CTech",
        "Fresh off a pivot to agents, the buzzy startup shipping fast raises $40M",
    ],
)
def test_parse_funding_title_negatives(title):
    assert parse_funding_title(title) is None, title


def test_billion_converted_to_millions():
    parsed = parse_funding_title("SambaNova raises $1.2 billion to expand")
    assert parsed["amount_millions"] == 1200.0


# ---------------------------------------------------------------- parse_feed on fixtures

def test_parse_feed_google_recency_and_dedupe():
    events = parse_feed(_load("funding_news_google.xml"), "google_news", 0.8, days=7, now=NOW)
    companies = [e["company"] for e in events]
    assert "Oratomic" in companies
    assert "Jota" in companies
    assert "Quantifind" in companies
    assert "KredosAi" in companies
    # Venice AI + Venice dedupe into one entry, first-seen name wins
    assert companies.count("Venice AI") == 1
    assert "Venice" not in companies
    # older than the 7-day window (Jul 1 before 12:00) — filtered
    assert "Aligned" not in companies
    assert "Telum Therapeutics" not in companies
    # non-funding titles never become events
    assert not any("CoreWeave" in c for c in companies)
    assert len(events) == 5


def test_parse_feed_google_wider_window_keeps_older():
    events = parse_feed(_load("funding_news_google.xml"), "google_news", 0.8, days=30, now=NOW)
    companies = {e["company"] for e in events}
    assert {"Aligned", "Telum Therapeutics"} <= companies
    assert len(events) == 7


def test_parse_feed_event_shape():
    events = parse_feed(_load("funding_news_google.xml"), "google_news", 0.8, days=7, now=NOW)
    for e in events:
        assert e["signal_type"] == "funding"
        assert isinstance(e["detail"], str) and e["detail"]
        assert e["source_url"].startswith("http")
        assert 0.0 < e["confidence"] <= 1.0
        assert e["published_at"] is None or "2026" in e["published_at"]
        assert e["source_name"]
    oratomic = next(e for e in events if e["company"] == "Oratomic")
    assert "$300" in oratomic["detail"]
    assert oratomic["source_name"] == "The Quantum Insider"


def test_parse_feed_techcrunch_filters_fund_noise():
    events = parse_feed(_load("funding_news_techcrunch.xml"), "techcrunch", 0.85, days=7, now=NOW)
    assert [e["company"] for e in events] == ["Norm"]
    assert events[0]["amount_millions"] == 120.0

    wider = parse_feed(_load("funding_news_techcrunch.xml"), "techcrunch", 0.85, days=30, now=NOW)
    assert {e["company"] for e in wider} == {"Norm", "Patronus AI"}


def test_parse_feed_crunchbase_roundups_yield_nothing():
    assert parse_feed(_load("funding_news_crunchbase.xml"), "crunchbase", 0.8, days=30, now=NOW) == []


def test_parse_feed_prnewswire_no_funding_today():
    assert parse_feed(_load("funding_news_prnewswire.xml"), "prnewswire", 0.7, days=30, now=NOW) == []


# ---------------------------------------------------------------- dedupe / normalize

def test_normalize_strips_suffixes():
    assert _normalize("Venice AI") == _normalize("Venice")
    assert _normalize("Acme, Inc.") == _normalize("Acme")
    assert _normalize("KredosAi") != _normalize("Kredos")


def test_dedupe_keeps_richest_record():
    poor = {"company": "Acme", "amount_millions": None, "round_type": None,
            "published_at": None, "source_name": "x"}
    rich = {"company": "Acme Inc", "amount_millions": 10.0, "round_type": "seed",
            "published_at": "2026-07-07", "source_name": "y"}
    deduped = _dedupe([poor, rich])
    assert len(deduped) == 1
    assert deduped[0]["amount_millions"] == 10.0


# ---------------------------------------------------------------- company_news

async def test_company_news_uses_google_query():
    fixture = _load("funding_news_google_company.xml")
    seen_urls: list[str] = []

    async def fake_fetch(session, url):
        seen_urls.append(url)
        return fixture

    with patch("scrapers.funding_news._fetch_text", fake_fetch):
        signals = await company_news("Anthropic", days=7)

    assert seen_urls and "Anthropic" in seen_urls[0].replace("%22", '"')
    assert signals, "expected signals from the fixture"
    for s in signals:
        assert s["signal_type"] in ("funding", "news")
        assert isinstance(s["detail"], str) and s["detail"]
        assert s["source_url"].startswith("http")
        assert 0.0 < s["confidence"] <= 1.0


async def test_company_news_survives_fetch_failure():
    async def dead_fetch(session, url):
        return None

    with patch("scrapers.funding_news._fetch_text", dead_fetch):
        assert await company_news("Anthropic") == []
