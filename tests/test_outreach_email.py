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
