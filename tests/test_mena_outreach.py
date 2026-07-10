"""Offline tests for mena_outreach.py — the caught-hiring freelance pitch."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mena_outreach import build_pitch


def _lead(**over) -> dict:
    lead = {
        "company": "Unilabs Middle East",
        "website": "unilabs.ae",
        "email": "info@unilabs.ae",
        "role_title": "Booking Coordinator",
        "category": "booking",
        "pain": "answering the same WhatsApp questions and confirming bookings by hand",
        "package": "WhatsApp Booking & Order Bot",
        "country": "United Arab Emirates",
        "city": "Abu Dhabi",
    }
    lead.update(over)
    return lead


def test_pitch_references_the_specific_role_and_company():
    subject, body = build_pitch(_lead())
    assert "Booking Coordinator" in subject or "Booking Coordinator" in body
    assert "Unilabs Middle East" in body


def test_pitch_uses_cost_anchor_and_70_percent_reframe():
    _, body = build_pitch(_lead())
    assert "/year" in body  # salary anchor
    assert "70%" in body
    # reframe: not "replace your hire"
    assert "replace" not in body.lower()


def test_pitch_has_low_friction_cta_and_signature():
    _, body = build_pitch(_lead())
    assert "reply" in body.lower()
    assert "Elie Haddad" in body
    assert "automation" in body.lower()


def test_pitch_mentions_arabic_moat_for_gulf():
    _, body = build_pitch(_lead(country="United Arab Emirates"))
    assert "Arabic" in body


def test_pitch_category_tailors_the_service_line():
    _, support = build_pitch(_lead(category="support", role_title="Customer Support Agent",
                                   package="AI Support Agent (EN/AR)"))
    assert "support" in support.lower()

    _, finance = build_pitch(_lead(category="finance", role_title="Accounts Clerk",
                                   package="Invoice & Cash-Flow Automation"))
    assert "invoice" in finance.lower() or "payment" in finance.lower()


def test_pitch_is_plain_text_no_placeholders_left():
    subject, body = build_pitch(_lead())
    for token in ["[First name]", "[Company]", "[role]", "{", "}", "~$Y", "[WhatsApp"]:
        assert token not in body, token
    assert subject and body
