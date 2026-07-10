"""Offline tests for scrapers/email_finder.py — real published-email extraction."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.email_finder import (
    _rank_emails,
    deobfuscate,
    extract_emails,
    find_email,
    normalize_domain,
    verify_mailbox,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _html() -> str:
    return (FIXTURES / "email_finder_contact.html").read_text(encoding="utf-8")


def _obfuscated() -> str:
    return (FIXTURES / "email_finder_obfuscated.html").read_text(encoding="utf-8")


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


def test_deobfuscate_common_tricks():
    text = deobfuscate("hello [at] acme [dot] io and sales(at)acme(dot)io")
    assert "hello@acme.io" in text
    assert "sales@acme.io" in text


def test_extract_emails_from_obfuscated_page():
    emails = extract_emails(_obfuscated(), "obfusco.io")
    for want in ["hello@obfusco.io", "sales@obfusco.io", "jane@obfusco.io",
                 "support@obfusco.io", "press@obfusco.io", "team@obfusco.io"]:
        assert want in emails, want
    assert "you@example.com" not in emails
    assert not any("png" in e for e in emails)


def test_verify_mailbox_accepts_and_rejects():
    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def helo(self, *a): return (250, b"ok")
        def ehlo(self, *a): return (250, b"ok")
        def mail(self, *a): return (250, b"ok")
        def rcpt(self, addr): return (250, b"ok") if "real" in addr else (550, b"no such user")

    with patch("scrapers.email_finder._mx_host", lambda d: "mx.acme.io"), \
         patch("scrapers.email_finder.smtplib.SMTP", FakeSMTP):
        assert verify_mailbox("real@acme.io") is True
        assert verify_mailbox("ghost@acme.io") is False


def test_verify_mailbox_unknown_when_blocked():
    def boom(*a, **k):
        raise OSError("port 25 blocked")

    with patch("scrapers.email_finder._mx_host", lambda d: "mx.acme.io"), \
         patch("scrapers.email_finder.smtplib.SMTP", boom):
        # blocked / unreachable probe must be inconclusive, not a false negative
        assert verify_mailbox("real@acme.io") is None


def test_mx_records_parses_windows_nslookup():
    from unittest.mock import MagicMock

    from scrapers import email_finder
    fake = MagicMock()
    fake.stdout = (
        "n8nlab.io\tMX preference = 5, mail exchanger = alt1.aspmx.l.google.com\n"
        "n8nlab.io\tMX preference = 1, mail exchanger = aspmx.l.google.com\n"
    )
    fake.stderr = ""
    with patch("scrapers.email_finder.subprocess.run", lambda *a, **k: fake):
        recs = email_finder._mx_records("n8nlab.io")
        assert recs[0] == (1, "aspmx.l.google.com")  # lowest preference first
        assert email_finder._mx_host("n8nlab.io") == "aspmx.l.google.com"
        assert email_finder.domain_has_mx("n8nlab.io") is True


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
