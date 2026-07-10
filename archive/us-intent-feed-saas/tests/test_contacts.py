"""Tests for scrapers/contacts.py — honest role-suggestion contact leads.

Fully offline and deterministic: the module performs no network I/O.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scrapers.contacts import email_patterns, get_contacts

# Keys core/pipeline.py (lines ~77-88) reads off each contact dict.
_PIPELINE_KEYS = {"first_name", "last_name", "title", "email", "linkedin_url", "source"}

_EXPECTED_TITLES = ["Founder / CEO", "VP of Sales / CRO", "Head of Growth / Marketing"]


# ---------------------------------------------------------------- email_patterns

def test_email_patterns_known_name():
    assert email_patterns("Jane", "Doe", "x.com") == [
        "jane.doe@x.com",
        "jane@x.com",
        "janedoe@x.com",
        "jdoe@x.com",
    ]


def test_email_patterns_normalizes_case_and_whitespace():
    patterns = email_patterns("  JANE ", "Doe ", " X.com")
    assert patterns[0] == "jane.doe@x.com"
    assert all(p == p.lower() for p in patterns)
    assert all(" " not in p for p in patterns)


def test_email_patterns_dedupes_single_letter_first_name():
    patterns = email_patterns("J", "Doe", "x.com")
    assert len(patterns) == len(set(patterns))


def test_email_patterns_bad_input_returns_empty():
    assert email_patterns("", "Doe", "x.com") == []
    assert email_patterns("Jane", "", "x.com") == []
    assert email_patterns("Jane", "Doe", "") == []


# ---------------------------------------------------------------- get_contacts

def test_get_contacts_shape_matches_pipeline():
    contacts = asyncio.run(get_contacts("acme.com", "Acme"))
    assert 3 <= len(contacts) <= 4
    for c in contacts:
        assert _PIPELINE_KEYS <= set(c.keys()), f"missing pipeline keys: {c.keys()}"
        assert c["company_domain"] == "acme.com"
        assert c["source"] == "role_suggestion"
        assert c["confidence"] == 0.3
        assert isinstance(c["title"], str) and c["title"]


def test_get_contacts_titles():
    contacts = asyncio.run(get_contacts("acme.com", "Acme"))
    titles = [c["title"] for c in contacts]
    for expected in _EXPECTED_TITLES:
        assert expected in titles


def test_get_contacts_never_fabricates_names():
    contacts = asyncio.run(get_contacts("acme.com", "Acme"))
    for c in contacts:
        assert c["first_name"] is None
        assert c["last_name"] is None


def test_get_contacts_generic_inbox_first_entry_only():
    contacts = asyncio.run(get_contacts("acme.com", "Acme"))
    assert contacts[0]["email"] == "hello@acme.com"
    for c in contacts[1:]:
        assert c["email"] is None


def test_get_contacts_linkedin_url_encoding():
    contacts = asyncio.run(get_contacts("acme.com", "Acme Rocket Co"))
    for c in contacts:
        url = c["linkedin_url"]
        assert url.startswith("https://www.linkedin.com/search/results/people/?keywords=")
        assert " " not in url, f"unencoded space in {url}"
        # company name with spaces must be percent/plus-encoded
        assert "Acme" in url and "Rocket" in url


def test_get_contacts_falls_back_to_domain_keywords():
    contacts = asyncio.run(get_contacts("acme.com"))
    assert contacts, "expected contacts with domain only"
    assert "acme.com" in contacts[0]["linkedin_url"]


def test_get_contacts_bad_input_returns_empty():
    assert asyncio.run(get_contacts("")) == []
    assert asyncio.run(get_contacts("   ")) == []
    assert asyncio.run(get_contacts(None)) == []  # type: ignore[arg-type]
