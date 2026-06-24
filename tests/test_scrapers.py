"""Scraper smoke tests — no API keys or DB required.

Run: python tests/test_scrapers.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scrapers.crunchbase import fetch_recent_funding
from scrapers.linkedin_jobs import scrape_jobs_for_company
from scrapers.website_monitor import check_website
from scrapers.apollo import get_contacts


async def test_crunchbase():
    events = await fetch_recent_funding(limit=5)
    assert isinstance(events, list), "Expected list"
    print(f"  crunchbase: {len(events)} funding events returned")
    if events:
        e = events[0]
        assert "title" in e and "signal_detail" in e, f"Missing keys: {e.keys()}"
        print(f"  sample: {e['signal_detail']}")


async def test_jobs():
    signals = await scrape_jobs_for_company("Stripe", limit=5)
    assert isinstance(signals, list), "Expected list"
    print(f"  jobs: {len(signals)} job signals for Stripe")
    if signals:
        s = signals[0]
        assert "signal_type" in s and "detail" in s, f"Missing keys: {s.keys()}"
        print(f"  sample: [{s['signal_type']}] {s['detail']}")


async def test_website():
    signals = await check_website("stripe.com")
    assert isinstance(signals, list), "Expected list"
    print(f"  website: {len(signals)} page signals for stripe.com")
    if signals:
        s = signals[0]
        assert "signal_type" in s and "detail" in s, f"Missing keys: {s.keys()}"
        print(f"  sample: {s['detail']} ({s['source_url']})")


async def test_apollo_contacts():
    contacts = await get_contacts("stripe.com")
    assert isinstance(contacts, list), "Expected list"
    assert len(contacts) > 0, "Expected at least one contact"
    for c in contacts:
        assert c.get("first_name"), f"Missing first_name: {c}"
        assert c.get("title"), f"Missing title: {c}"
        assert "email_patterns" in c, f"Missing email_patterns: {c}"
    print(f"  contacts: {len(contacts)} pattern-inferred contacts for stripe.com")
    print(f"  sample: {contacts[0]['title']} -> {contacts[0]['most_likely_email']}")


TESTS = [
    ("crunchbase", test_crunchbase),
    ("jobs (Indeed RSS)", test_jobs),
    ("website monitor", test_website),
    ("apollo contacts", test_apollo_contacts),
]


async def main():
    print("=" * 55)
    print("Opportunity Radar — Scraper Tests")
    print("=" * 55)
    passed = failed = 0
    for name, fn in TESTS:
        print(f"\n[{name}]")
        try:
            await fn()
            print(f"  >> PASS")
            passed += 1
        except Exception as e:
            print(f"  >> FAIL: {e}")
            failed += 1
    print(f"\n{'='*55}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
