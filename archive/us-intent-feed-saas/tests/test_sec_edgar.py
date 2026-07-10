"""SEC EDGAR Form D scraper tests — offline, fixture-driven.

Fixtures captured live from efts.sec.gov / www.sec.gov on 2026-07-08:
  tests/fixtures/sec_edgar_search.json           — 9 real search hits (funds, operating cos, one D/A)
  tests/fixtures/sec_edgar_primary_doc.xml       — Poaster Technologies Inc. (operating raise)
  tests/fixtures/sec_edgar_primary_doc_fund.xml  — Volantis I, LP (pooled investment fund)

Run: .venv/Scripts/python.exe -m pytest tests/test_sec_edgar.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scrapers.sec_edgar import (
    _build_detail,
    _filter_hits,
    _parse_primary_doc,
    is_pooled_fund,
    parse_search_hits,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_payload() -> dict:
    with open(_FIXTURES / "sec_edgar_search.json", encoding="utf-8") as f:
        return json.load(f)


def _hit(payload: dict, adsh: str) -> dict:
    for h in payload["hits"]["hits"]:
        if h["_source"]["adsh"] == adsh:
            return h
    raise KeyError(adsh)


# ---------------------------------------------------------------- parse_search_hits

def test_parse_search_hits_returns_all_hits_unfiltered():
    payload = _load_payload()
    events = parse_search_hits(payload)
    # no noise filtering at parse level: all 9 hits (incl. funds and the D/A) come back
    assert len(events) == 9
    for e in events:
        assert e["signal_type"] == "funding"
        assert isinstance(e["confidence"], float) and e["confidence"] == 0.85
        assert e["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/")
        assert e["amount_millions"] is None  # no detail fetch yet


def test_parse_search_hits_field_mapping():
    payload = _load_payload()
    events = parse_search_hits(payload)
    poaster = next(e for e in events if e["cik"] == 2143918)
    assert poaster["company"] == "Poaster Technologies Inc."
    assert poaster["filed_at"] == "2026-07-07"
    assert poaster["location"] == "Brooklyn, NY"
    assert "Form D" in poaster["detail"]
    assert "/2143918/" in poaster["source_url"]
    assert "000214391826000001" in poaster["source_url"]


def test_parse_search_hits_bad_payload_returns_empty():
    assert parse_search_hits({}) == []
    assert parse_search_hits({"hits": {}}) == []


# ---------------------------------------------------------------- is_pooled_fund

def test_is_pooled_fund_by_3c_items():
    payload = _load_payload()
    # Volantis I, LP — items ['06B', '3C', '3C.1']
    assert is_pooled_fund(_hit(payload, "0002144231-26-000001")) is True
    # Canal Grande Fund II LP — items ['06B', '3C', '3C.7']
    assert is_pooled_fund(_hit(payload, "0002144012-26-000001")) is True


def test_is_pooled_fund_by_name_pattern():
    payload = _load_payload()
    # Revolve Partners II, LP — items ['06B'] only, fund by name
    assert is_pooled_fund(_hit(payload, "0002143943-26-000001")) is True
    # OurCrowd (Investment in And) L.P. — SPV-style investment vehicle
    assert is_pooled_fund(_hit(payload, "0002143992-26-000001")) is True
    # Eave Capital Partners LP
    assert is_pooled_fund(_hit(payload, "0002139388-26-000003")) is True


def test_is_pooled_fund_operating_companies_pass():
    payload = _load_payload()
    for adsh in (
        "0002143918-26-000001",  # Poaster Technologies Inc.
        "0002143681-26-000001",  # Kyma Concepts, Inc.
        "0002143657-26-000001",  # Genesis Computing Inc.
        "0002144211-26-000001",  # Northstar Baseball Group, LLC
    ):
        assert is_pooled_fund(_hit(payload, adsh)) is False, adsh


# ---------------------------------------------------------------- hit filtering (fetch path)

def test_filter_hits_keeps_only_operating_form_d():
    payload = _load_payload()
    kept = _filter_hits(payload["hits"]["hits"])
    names = sorted(h["_source"]["display_names"][0].split("  (CIK")[0] for h in kept)
    assert names == [
        "Genesis Computing Inc.",
        "Kyma Concepts, Inc.",
        "Northstar Baseball Group, LLC",
        "Poaster Technologies Inc.",
    ]
    # the D/A amendment must be gone even though it is also a fund by name
    assert all(h["_source"]["file_type"] == "D" for h in kept)


# ---------------------------------------------------------------- primary_doc.xml parsing

def test_primary_doc_amount_extraction():
    xml = (_FIXTURES / "sec_edgar_primary_doc.xml").read_text(encoding="utf-8")
    doc = _parse_primary_doc(xml)
    assert doc["entity_name"] == "Poaster Technologies Inc."
    assert doc["industry_group"] == "Other Technology"
    assert doc["total_offering_amount"] == 59999879.0
    assert doc["total_amount_sold"] == 54776949.0


def test_primary_doc_pooled_fund_industry():
    xml = (_FIXTURES / "sec_edgar_primary_doc_fund.xml").read_text(encoding="utf-8")
    doc = _parse_primary_doc(xml)
    assert doc["entity_name"] == "Volantis I, LP"
    assert doc["industry_group"] == "Pooled Investment Fund"
    assert doc["total_amount_sold"] == 0.0


def test_primary_doc_indefinite_amount_is_none():
    xml = (_FIXTURES / "sec_edgar_primary_doc.xml").read_text(encoding="utf-8")
    xml = xml.replace(
        "<totalOfferingAmount>59999879</totalOfferingAmount>",
        "<totalOfferingAmount>Indefinite</totalOfferingAmount>",
    )
    doc = _parse_primary_doc(xml)
    assert doc["total_offering_amount"] is None
    assert doc["total_amount_sold"] == 54776949.0


# ---------------------------------------------------------------- detail string building

def test_build_detail_from_amounts():
    amount, detail = _build_detail(54776949.0, 59999879.0)
    assert amount == 54.776949
    assert detail == "Filed SEC Form D — raised $54.8M"

    amount, detail = _build_detail(0.0, 25000000.0)
    assert amount == 25.0
    assert detail == "Filed SEC Form D — offering up to $25M"

    amount, detail = _build_detail(None, None)
    assert amount is None
    assert detail == "Filed SEC Form D (exempt offering)"
