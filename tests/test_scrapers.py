"""Live smoke tests for the scraper suite (network required, tolerant of
empty results — a blocked feed must not fail CI, but a shape change must).

Offline unit tests live in test_funding_news.py, test_job_boards.py,
test_sec_edgar.py, test_hn_hiring.py, test_contacts.py.

Run directly: python tests/test_scrapers.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers.contacts import get_contacts
from scrapers.funding_news import fetch_funding_events
from scrapers.hn_hiring import fetch_hiring_posts
from scrapers.job_boards import gtm_hiring_summary
from scrapers.sec_edgar import fetch_form_d_filings
from scrapers.website_monitor import check_website


async def test_funding_news_live():
    events = await fetch_funding_events(days=7, limit=20)
    assert isinstance(events, list)
    if events:
        e = events[0]
        assert "company" in e and "detail" in e and e["signal_type"] == "funding"
        print(f"  sample: {e['company']} — {e['detail']}")
    print(f"  {len(events)} funding events")


async def test_job_boards_live():
    summary = await gtm_hiring_summary("Vercel", "vercel.com")
    assert isinstance(summary, dict)
    if summary:
        assert "board" in summary and "gtm_jobs" in summary
        print(f"  vercel: {summary['gtm_jobs']} GTM roles on {summary['board']}")


async def test_hn_hiring_live():
    posts = await fetch_hiring_posts(limit=50)
    assert isinstance(posts, list)
    if posts:
        p = posts[0]
        assert "company" in p and "detail" in p and p["signal_type"] == "hiring"
        print(f"  sample: {p['company']}")
    print(f"  {len(posts)} HN hiring posts")


async def test_sec_edgar_live():
    filings = await fetch_form_d_filings(days=3, limit=10, detail_limit=2)
    assert isinstance(filings, list)
    if filings:
        f = filings[0]
        assert "company" in f and f["signal_type"] == "funding"
        print(f"  sample: {f['company']} — {f['detail']}")
    print(f"  {len(filings)} Form D filings")


async def test_website_monitor_live():
    signals = await check_website("stripe.com")
    assert isinstance(signals, list)
    if signals:
        assert "signal_type" in signals[0] and "detail" in signals[0]
    print(f"  {len(signals)} website signals")


async def test_contacts_deterministic():
    contacts = await get_contacts("stripe.com", "Stripe")
    assert len(contacts) > 0
    for c in contacts:
        # honest output: role suggestions only, never fabricated people
        assert c["first_name"] is None and c["last_name"] is None
        assert c["title"] and c["linkedin_url"].startswith("https://")
    print(f"  {len(contacts)} role suggestions")


TESTS = [
    ("funding_news live", test_funding_news_live),
    ("job_boards live", test_job_boards_live),
    ("hn_hiring live", test_hn_hiring_live),
    ("sec_edgar live", test_sec_edgar_live),
    ("website_monitor live", test_website_monitor_live),
    ("contacts deterministic", test_contacts_deterministic),
]


async def main() -> int:
    failed = 0
    for name, fn in TESTS:
        print(f"[TEST] {name}")
        try:
            await fn()
            print(f"[PASS] {name}\n")
        except Exception as e:
            failed += 1
            print(f"[FAIL] {name}: {e}\n")
    print(f"{'=' * 50}\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
