"""Tests for the product-selling outreach email in send_outreach.py."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from send_outreach import _build_email, _load_teaser


def _row(**overrides) -> dict:
    row = {
        "Company": "Acme Automation",
        "Category": "AI Automation",
        "Website": "acme.io",
        "Founder": "Jane Doe",
        "Niche / Specialty": "n8n workflows for B2B",
        "Email": "",
    }
    row.update(overrides)
    return row


TEASER = [
    "Patronus AI — raised $30M Series B, hiring 4 GTM roles",
    "Agave — raised $15M Series A on Jul 3",
    "Northstar Group — filed SEC Form D for $22.5M",
]


def test_email_sells_the_product_not_freelancing():
    subject, body = _build_email(_row(), "hello@acme.io", TEASER)
    combined = f"{subject}\n{body}".lower()
    assert "freelance" not in combined
    assert "contract work" not in combined
    # sells a lead feed with a price and a reply CTA
    assert "$149" in body
    assert "reply" in body.lower()
    assert "free" in body.lower()


def test_email_includes_teaser_leads():
    _, body = _build_email(_row(), "hello@acme.io", TEASER)
    assert "Patronus AI" in body
    assert "Agave" in body
    assert "Northstar Group" in body


def test_email_personalization():
    subject, body = _build_email(_row(), "hello@acme.io", TEASER)
    assert body.startswith("Hi Jane,")
    assert "Acme Automation" in subject or "Acme Automation" in body

    _, body_anon = _build_email(_row(Founder=""), "hello@acme.io", TEASER)
    assert body_anon.startswith("Hi there,")


def test_email_survives_empty_teaser():
    subject, body = _build_email(_row(), "hello@acme.io", [])
    assert subject
    assert "$149" in body


def test_load_teaser_reads_newest_report(tmp_path: Path):
    old = tmp_path / "intent_report_2026-07-01.csv"
    new = tmp_path / "intent_report_2026-07-08.csv"
    for path, company in ((old, "OldCo"), (new, "NewCo")):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["Company", "Score", "Signals", "FundingDetail", "GTMOpenRoles"]
            )
            writer.writeheader()
            writer.writerow(
                {
                    "Company": company,
                    "Score": "88",
                    "Signals": "funding; hiring",
                    "FundingDetail": "Raised $10M Series A",
                    "GTMOpenRoles": "3",
                }
            )
    lines = _load_teaser(tmp_path)
    assert lines, "expected teaser lines from newest report"
    assert any("NewCo" in line for line in lines)
    assert all("OldCo" not in line for line in lines)


def test_load_teaser_missing_dir(tmp_path: Path):
    assert _load_teaser(tmp_path / "nope") == []


def test_guess_emails_ignores_non_address_in_email_column():
    from send_outreach import _guess_emails

    # data-entry error: a person's name in the Email column must not be
    # used as a recipient; fall back to website-based guessing
    row = _row(Email="Jane Doe", Website="tc9.ai", Founder="")
    emails = _guess_emails(row)
    assert all("@" in e for e in emails)
    assert "hello@tc9.ai" in emails

    real = _guess_emails(_row(Email="real@example.com"))
    assert real == ["real@example.com"]


# ── verified-only resolution (never send to a fabricated address) ─────────────

import asyncio
from unittest.mock import patch

from send_outreach import resolve_email


def test_resolve_email_trusts_explicit_when_domain_has_mx():
    with patch("send_outreach.domain_has_mx", lambda d: True):
        email, source = asyncio.run(resolve_email(_row(Email="jane@acme.io")))
    assert email == "jane@acme.io"
    assert source == "csv"


def test_resolve_email_scrapes_when_no_explicit():
    async def fake_find(domain, company=None):
        return {"email": "hello@acme.io", "mx_ok": True, "all_emails": ["hello@acme.io"],
                "contact_url": "https://acme.io", "source": "website"}

    with patch("send_outreach.find_email", fake_find), \
         patch("send_outreach.domain_has_mx", lambda d: True):
        email, source = asyncio.run(resolve_email(_row(Email="", Website="acme.io")))
    assert email == "hello@acme.io"
    assert source == "scraped"


def test_resolve_email_returns_none_when_unverifiable():
    async def fake_find(domain, company=None):
        return {"email": None, "mx_ok": False, "all_emails": [],
                "contact_url": "https://x.io", "source": "contact_page"}

    with patch("send_outreach.find_email", fake_find), \
         patch("send_outreach.domain_has_mx", lambda d: False):
        email, source = asyncio.run(resolve_email(_row(Email="", Website="x.io")))
    # never fabricate: no verified address means no send
    assert email is None
    assert source == "none"


def test_resolve_email_rejects_explicit_on_dead_domain_then_scrapes():
    async def fake_find(domain, company=None):
        return {"email": "team@acme.io", "mx_ok": True, "all_emails": ["team@acme.io"],
                "contact_url": "https://acme.io", "source": "website"}

    # explicit address is on a domain with no MX -> don't trust it, scrape instead
    def mx(d):
        return d != "dead.io"

    with patch("send_outreach.find_email", fake_find), \
         patch("send_outreach.domain_has_mx", mx):
        email, source = asyncio.run(
            resolve_email(_row(Email="x@dead.io", Website="acme.io"))
        )
    assert email == "team@acme.io"
    assert source == "scraped"
