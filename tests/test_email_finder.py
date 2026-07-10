"""Offline tests for scrapers/email_finder.py — real published-email extraction."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.email_finder import (
    _rank_emails,
    extract_emails,
    find_email,
    normalize_domain,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _html() -> str:
    return (FIXTURES / "email_finder_contact.html").read_text(encoding="utf-8")


def test_extract_emails_finds_real_addresses():
    emails = extract_emails(_html(), "acme.io")
    assert "hello@acme.io" in emails
    assert "jane@acme.io" in emails
    assert "careers@acme.io" in emails
    assert "support@acme.io" in emails


def test_extract_emails_filters_junk():
    emails = extract_emails(_html(), "acme.io")
    # image assets, sentry DSNs, placeholders, third-party badges must be gone
    assert not any("png" in e or "sentry" in e for e in emails)
    assert "name@example.com" not in emails
    assert "user@domain.com" not in emails
    assert "verified@trustpilot.com" not in emails  # off-domain third party
    # every returned address is on the target domain
    assert all(e.endswith("@acme.io") for e in emails)


def test_extract_emails_deduplicates():
    emails = extract_emails(_html(), "acme.io")
    assert len(emails) == len(set(emails))


def test_rank_prefers_personal_then_role_inbox():
    ranked = _rank_emails(
        ["support@acme.io", "careers@acme.io", "hello@acme.io", "jane@acme.io"],
        "acme.io",
    )
    # a personal-looking address ranks above generic role inboxes
    assert ranked[0] == "jane@acme.io"
    # hello/contact/info outrank support/careers/noreply
    assert ranked.index("hello@acme.io") < ranked.index("support@acme.io")
    assert ranked.index("hello@acme.io") < ranked.index("careers@acme.io")


def test_rank_drops_noreply_and_legal_last():
    ranked = _rank_emails(["noreply@acme.io", "hello@acme.io", "legal@acme.io"], "acme.io")
    assert ranked[0] == "hello@acme.io"
    assert ranked[-1] == "noreply@acme.io"


def test_normalize_domain():
    assert normalize_domain("https://www.acme.io/contact") == "acme.io"
    assert normalize_domain("ACME.io") == "acme.io"
    assert normalize_domain("http://acme.io") == "acme.io"
    assert normalize_domain("") == ""


async def test_find_email_returns_best_verified_address():
    async def fake_fetch(session, url):
        # homepage has no email; the /contact page does
        return _html() if "contact" in url else "<html><body>nothing</body></html>"

    with patch("scrapers.email_finder._fetch_text", fake_fetch), \
         patch("scrapers.email_finder.domain_has_mx", lambda d: True):
        result = await find_email("acme.io", "Acme Automation")

    assert result["email"] == "jane@acme.io"
    assert result["mx_ok"] is True
    assert "hello@acme.io" in result["all_emails"]
    assert result["contact_url"].endswith("/contact") or result["contact_url"] == "https://acme.io"
    assert result["source"] == "website"


async def test_find_email_no_email_falls_back_to_contact_url():
    async def fake_fetch(session, url):
        return "<html><body>No addresses here, use the form.</body></html>"

    with patch("scrapers.email_finder._fetch_text", fake_fetch), \
         patch("scrapers.email_finder.domain_has_mx", lambda d: True):
        result = await find_email("noemail.io")

    assert result["email"] is None
    assert result["all_emails"] == []
    assert result["contact_url"]  # a page a human can use
    assert result["source"] == "contact_page"


async def test_find_email_dead_domain_flagged():
    async def fake_fetch(session, url):
        return None  # nothing resolves

    with patch("scrapers.email_finder._fetch_text", fake_fetch), \
         patch("scrapers.email_finder.domain_has_mx", lambda d: False):
        result = await find_email("dead.example")

    assert result["email"] is None
    assert result["mx_ok"] is False


async def test_find_email_skips_send_when_no_mx():
    # domain resolves a page with an address, but the domain can't receive mail
    async def fake_fetch(session, url):
        return _html() if "contact" in url else "<html></html>"

    with patch("scrapers.email_finder._fetch_text", fake_fetch), \
         patch("scrapers.email_finder.domain_has_mx", lambda d: False):
        result = await find_email("acme.io")

    # emails were found but mx_ok gates sending
    assert result["all_emails"]
    assert result["mx_ok"] is False


def test_find_email_bad_input():
    import asyncio
    assert asyncio.run(find_email(""))["email"] is None
