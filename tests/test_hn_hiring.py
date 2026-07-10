"""HN 'Who is hiring' scraper tests — offline, fixture-driven.

Fixture captured live from the Algolia API on 2026-07-08:
  discovery: /api/v1/search_by_date?query="who is hiring"&tags=story,author_whoishiring
  thread:    /api/v1/items/48747976 (July 2026), trimmed to 6 real top-level posts
             plus one synthetic text=null entry (dead/flagged skip path).

Run: .venv/Scripts/python.exe -m pytest tests/test_hn_hiring.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

from scrapers.hn_hiring import (
    _extract_signals,
    _pick_thread_id,
    fetch_hiring_posts,
    parse_post,
)

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "hn_hiring_fixture.json").read_text(encoding="utf-8")
)
_POSTS = {c["id"]: c["text"] for c in _FIXTURE["thread"]["children"]}


# ---------------------------------------------------------------- parse_post

def test_parse_location_first_order():
    # "Blaine, WA | CaseLight Systems Inc. (CSI) | ... | Founding Systems Engineer | ..."
    p = parse_post(_POSTS[48747987])
    assert p is not None
    assert p["company"] == "CaseLight Systems Inc. (CSI)"
    assert p["location"] == "Blaine, WA"
    assert p["remote"] is True
    assert "Founding Systems Engineer" in p["roles"]
    assert p["funding_stage"] is None
    assert len(p["snippet"]) <= 200


def test_parse_company_first_order_with_funding():
    # "WireScreen (Series A) | Senior Software Engineer (Frontend) &amp; Machine Learning Engineer | NYC - hybrid | ..."
    p = parse_post(_POSTS[48748008])
    assert p is not None
    assert p["company"] == "WireScreen"  # "(Series A)" suffix stripped
    assert p["funding_stage"] == "series a"
    assert p["remote"] is False
    assert p["location"] is not None and "NYC" in p["location"]
    assert any("Machine Learning Engineer" in r for r in p["roles"])
    assert not any("&amp;" in r for r in p["roles"])  # entities unescaped


def test_parse_entity_unescaping():
    # "We The Flywheel | AI-Native Engineers &amp; Operators | REMOTE (worldwide) | Contract &#x2F; Part-time ..."
    p = parse_post(_POSTS[48747990])
    assert p is not None
    assert p["company"] == "We The Flywheel"
    assert p["remote"] is True
    assert "&amp;" not in p["snippet"] and "&#x2F;" not in p["snippet"]
    assert "&" in p["snippet"] and "/" in p["snippet"]
    assert any("Engineer" in r for r in p["roles"])
    assert p["has_gtm_roles"] is True  # "growth" in body


def test_parse_gtm_roles_detected():
    # "FusionAuth | Principal Software Engineer, Senior Java Engineer - Cloud, Account Executive | ..."
    p = parse_post(_POSTS[48794583])
    assert p is not None
    assert p["company"] == "FusionAuth"
    assert p["has_gtm_roles"] is True
    assert any("Account Executive" in r for r in p["roles"])
    assert len(p["roles"]) == 3
    assert p["remote"] is True


def test_parse_gtm_negative():
    # WireScreen post has no sales/growth/marketing/revenue mentions
    p = parse_post(_POSTS[48748008])
    assert p is not None
    assert p["has_gtm_roles"] is False


def test_funding_stage_priority_series_over_bootstrapped():
    # SmarterDx body mentions both "bootstrapped" and "$50M Series B" — series wins
    p = parse_post(_POSTS[48748003])
    assert p is not None
    assert p["company"] == "SmarterDx"
    assert p["funding_stage"] == "series b"
    assert p["has_gtm_roles"] is True  # "revenue" in body


def test_parse_unparseable_returns_none():
    # real non-job comment: "don&#x27;t waste your time with these guys"
    assert parse_post(_POSTS[48749297]) is None
    assert parse_post("") is None
    assert parse_post(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------- discovery

def test_pick_thread_id_from_live_discovery():
    assert _pick_thread_id(_FIXTURE["discovery"]) == 48747976


def test_pick_thread_id_skips_sibling_threads():
    hits = {
        "hits": [
            {"objectID": "111", "title": "Ask HN: Who wants to be hired? (July 2026)"},
            {"objectID": "222", "title": "Ask HN: Freelancer? Seeking freelancer? (July 2026)"},
            {"objectID": "333", "title": "Ask HN: Who is hiring? (July 2026)"},
        ]
    }
    assert _pick_thread_id(hits) == 333
    assert _pick_thread_id({"hits": []}) is None


# ---------------------------------------------------------------- signals

def test_extract_signals_canonical_shape():
    signals = _extract_signals(_FIXTURE["thread"])
    # 7 children: 1 text=null (skipped), 1 unparseable (skipped) -> 5 signals
    assert len(signals) == 5
    for s in signals:
        assert s["signal_type"] == "hiring"
        assert isinstance(s["detail"], str) and s["detail"]
        assert s["source_url"].startswith("https://news.ycombinator.com/item?id=")
        assert 0.6 <= s["confidence"] <= 0.8
        assert s["company"]
    by_url = {s["source_url"]: s for s in signals}
    fusion = by_url["https://news.ycombinator.com/item?id=48794583"]
    assert fusion["detail"] == "Hiring 3 roles incl. Account Executive (HN Who is Hiring)"


def test_extract_signals_respects_limit():
    assert len(_extract_signals(_FIXTURE["thread"], limit=2)) == 2


async def test_fetch_hiring_posts_offline(monkeypatch):
    import scrapers.hn_hiring as mod

    async def fake_get_json(session, url):
        return _FIXTURE["discovery"] if "search_by_date" in url else _FIXTURE["thread"]

    monkeypatch.setattr(mod, "_get_json", fake_get_json)
    posts = await fetch_hiring_posts(limit=3)
    assert len(posts) == 3
    assert all(p["signal_type"] == "hiring" for p in posts)
