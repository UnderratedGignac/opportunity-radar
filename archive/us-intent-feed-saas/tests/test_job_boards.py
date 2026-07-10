"""Tests for scrapers/job_boards.py — Greenhouse / Lever / Ashby ATS probing.

All tests run OFFLINE. Fixtures under tests/fixtures/job_boards_* are trimmed
real payloads captured 2026-07-08 from:
  - https://boards-api.greenhouse.io/v1/boards/vercel/jobs
  - https://api.lever.co/v0/postings/mistral?mode=json&limit=5
  - https://api.ashbyhq.com/posting-api/job-board/linear
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.job_boards import (
    _parse_ashby,
    _parse_greenhouse,
    _parse_lever,
    classify_gtm_role,
    gtm_hiring_summary,
    scan_company_jobs,
    slug_candidates,
)

FIXTURES = Path(__file__).parent / "fixtures"
_ALLOWED_TYPES = {"funding", "hiring", "exec_change", "tech_change", "website_change", "news"}


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _router(routes: list[tuple[str, tuple[int, object]]]):
    """Fake for job_boards._get_json: match URL prefix -> (status, json). Default 404."""
    calls: list[str] = []

    async def fake(session, url):
        calls.append(url)
        for prefix, resp in routes:
            if url.startswith(prefix):
                return resp
        return 404, None

    fake.calls = calls
    return fake


def _assert_canonical(sig: dict):
    assert sig["signal_type"] in _ALLOWED_TYPES
    assert isinstance(sig["detail"], str) and sig["detail"]
    assert isinstance(sig["source_url"], str) and sig["source_url"].startswith("http")
    assert isinstance(sig["confidence"], float) and 0.0 <= sig["confidence"] <= 1.0


# ---------------------------------------------------------------- slug_candidates

def test_slug_candidates_company_and_domain():
    assert slug_candidates("Patronus AI", "patronusai.com") == [
        "patronusai",
        "patronus-ai",
        "patronus",
    ]


def test_slug_candidates_no_domain():
    assert slug_candidates("Patronus AI") == ["patronusai", "patronus-ai", "patronus"]


def test_slug_candidates_single_word_dedupes():
    assert slug_candidates("Vercel", "vercel.com") == ["vercel"]


def test_slug_candidates_lowercase_max3():
    cands = slug_candidates("Full Send Media Group", "fullsend.io")
    assert len(cands) <= 3
    assert all(c == c.lower() for c in cands)
    assert cands[0] == "fullsend"
    assert len(cands) == len(set(cands))


def test_slug_candidates_strips_www_and_scheme():
    assert slug_candidates("Linear", "https://www.linear.app")[0] == "linear"


# ---------------------------------------------------------------- classify_gtm_role

@pytest.mark.parametrize(
    "title,expected_type,expected_weight",
    [
        ("Founding Account Executive", "hiring", 32),
        ("Enterprise Account Executive", "hiring", 25),
        ("Account Executive, Majors", "hiring", 25),
        ("VP of Sales", "exec_change", 35),
        ("Head of Sales, EMEA", "exec_change", 35),
        ("Sales Manager", "hiring", 24),
        ("GTM Lead", "hiring", 26),
        ("Growth Lead", "hiring", 22),
        ("Head of Partnerships", "hiring", 20),
        ("Senior Sales Engineer", "hiring", 22),
        ("Demand Generation Manager", "hiring", 24),
        ("Sales Enablement Specialist", "hiring", 20),
        ("SDR - New York", "hiring", 28),
        ("Chief Revenue Officer", "exec_change", 35),
        ("Customer Success Manager", "hiring", 20),
        ("Growth Marketing Manager, Agent Stack ", "hiring", 22),
    ],
)
def test_classify_gtm_role_positives(title, expected_type, expected_weight):
    role = classify_gtm_role(title)
    assert role is not None, title
    assert role["signal_type"] == expected_type
    assert role["base_weight"] == expected_weight
    assert isinstance(role["detail"], str) and role["detail"]


@pytest.mark.parametrize(
    "title",
    [
        "Senior Software Engineer",
        "Senior / Staff Fullstack Engineer",
        "Product Designer",
        "Engineering Manager, CDN",
        "Developer Success Engineer",
        "Data Scientist",
        "Recruiting & HR Operations Specialist",
        "",
    ],
)
def test_classify_gtm_role_negatives(title):
    assert classify_gtm_role(title) is None


def test_classify_founding_ae_beats_plain_ae():
    # longest keyword must win
    assert classify_gtm_role("Founding Account Executive (SF)")["base_weight"] == 32


# ---------------------------------------------------------------- per-board parsing

def test_parse_greenhouse_fixture():
    payload = _load("job_boards_greenhouse_vercel.json")
    jobs = _parse_greenhouse(payload)
    assert len(jobs) == 4
    titles = {j["title"] for j in jobs}
    assert "Account Executive, Majors" in titles
    ae = next(j for j in jobs if j["title"] == "Account Executive, Majors")
    assert ae["url"] == "https://job-boards.greenhouse.io/vercel/jobs/5999792004"
    # first_published is used for recency, parsed tz-aware
    assert ae["published_at"] == datetime.fromisoformat("2026-05-21T09:26:09-04:00")
    assert ae["published_at"].tzinfo is not None


def test_parse_lever_fixture_sorts_and_converts_epoch_ms():
    payload = _load("job_boards_lever_mistral.json")
    jobs = _parse_lever(payload)
    assert len(jobs) == 5
    # Lever feed is not sorted — parser must sort newest-first client-side
    stamps = [j["published_at"] for j in jobs]
    assert stamps == sorted(stamps, reverse=True)
    newest = jobs[0]
    assert newest["title"] == "Account Executive, Enterprise - New York"
    # createdAt 1766091135357 is EPOCH MILLISECONDS
    assert newest["published_at"] == datetime.fromtimestamp(
        1766091135357 / 1000, tz=timezone.utc
    )
    assert newest["url"].startswith("https://jobs.lever.co/mistral/")


def test_parse_ashby_fixture():
    payload = _load("job_boards_ashby_linear.json")
    jobs = _parse_ashby(payload)
    assert len(jobs) == 4
    csm = next(j for j in jobs if j["title"] == "Customer Success Manager")
    assert csm["published_at"] == datetime.fromisoformat("2026-06-17T13:18:43.591+00:00")
    assert csm["url"] == "https://jobs.ashbyhq.com/linear/370d9605-f02f-44f9-97fa-ebf769bed93d"


# ---------------------------------------------------------------- scan_company_jobs

async def test_scan_greenhouse_fixture_signals():
    fake = _router(
        [("https://boards-api.greenhouse.io/v1/boards/vercel/jobs",
          (200, _load("job_boards_greenhouse_vercel.json")))]
    )
    with patch("scrapers.job_boards._get_json", fake):
        signals = await scan_company_jobs("Vercel", "vercel.com", recent_days=36500)
    roles = {s["role_title"] for s in signals}
    assert roles == {"Account Executive, Majors", "Growth Marketing Manager, Agent Stack "}
    for s in signals:
        _assert_canonical(s)
        assert s["company"] == "Vercel"
        assert s["board"] == "greenhouse"


async def test_scan_greenhouse_recency_filter():
    now = datetime.now(timezone.utc)
    payload = {
        "jobs": [
            {"title": "Account Executive, Recent", "absolute_url": "https://x.gh/1",
             "first_published": (now - timedelta(days=5)).isoformat()},
            {"title": "Account Executive, Stale", "absolute_url": "https://x.gh/2",
             "first_published": (now - timedelta(days=90)).isoformat()},
        ],
        "meta": {"total": 2},
    }
    fake = _router([("https://boards-api.greenhouse.io/v1/boards/acme/jobs", (200, payload))])
    with patch("scrapers.job_boards._get_json", fake):
        signals = await scan_company_jobs("Acme", recent_days=30)
    assert [s["role_title"] for s in signals] == ["Account Executive, Recent"]


async def test_scan_lever_recency_filter_epoch_ms():
    now = datetime.now(timezone.utc)
    recent_ms = int((now - timedelta(days=5)).timestamp() * 1000)
    stale_ms = int((now - timedelta(days=200)).timestamp() * 1000)
    payload = [
        {"text": "Sales Manager, Stale", "createdAt": stale_ms,
         "hostedUrl": "https://jobs.lever.co/acme/2", "categories": {"team": "Sales"}},
        {"text": "Sales Manager, Recent", "createdAt": recent_ms,
         "hostedUrl": "https://jobs.lever.co/acme/1", "categories": {"team": "Sales"}},
    ]
    fake = _router(
        [
            ("https://boards-api.greenhouse.io/", (404, None)),
            ("https://api.lever.co/v0/postings/acme", (200, payload)),
        ]
    )
    with patch("scrapers.job_boards._get_json", fake):
        signals = await scan_company_jobs("Acme", recent_days=30)
    assert [s["role_title"] for s in signals] == ["Sales Manager, Recent"]
    assert signals[0]["board"] == "lever"


async def test_scan_ashby_recency_filter_iso():
    now = datetime.now(timezone.utc)
    payload = {
        "jobs": [
            # Ashby keeps the ORIGINAL publish date — old postings must be filtered out
            {"title": "Account Executive, Startups", "jobUrl": "https://jobs.ashbyhq.com/acme/1",
             "publishedAt": (now - timedelta(days=400)).isoformat(), "isListed": True},
            {"title": "Customer Success Manager", "jobUrl": "https://jobs.ashbyhq.com/acme/2",
             "publishedAt": (now - timedelta(days=5)).isoformat(), "isListed": True},
        ],
        "apiVersion": "1",
    }
    fake = _router(
        [
            ("https://boards-api.greenhouse.io/", (404, None)),
            ("https://api.lever.co/", (200, [])),  # 200 + [] == not on Lever
            ("https://api.ashbyhq.com/posting-api/job-board/acme", (200, payload)),
        ]
    )
    with patch("scrapers.job_boards._get_json", fake):
        signals = await scan_company_jobs("Acme", recent_days=30)
    assert [s["role_title"] for s in signals] == ["Customer Success Manager"]
    assert signals[0]["board"] == "ashby"


async def test_probe_order_first_hit_wins_and_bounded():
    ashby_payload = _load("job_boards_ashby_linear.json")
    fake = _router(
        [
            ("https://boards-api.greenhouse.io/", (404, None)),
            ("https://api.lever.co/", (200, [])),
            # first ashby slug is a miss (200 with empty jobs), second hits
            ("https://api.ashbyhq.com/posting-api/job-board/patronusai", (200, {"jobs": []})),
            ("https://api.ashbyhq.com/posting-api/job-board/patronus-ai", (200, ashby_payload)),
        ]
    )
    with patch("scrapers.job_boards._get_json", fake):
        signals = await scan_company_jobs("Patronus AI", "patronusai.com", recent_days=36500)
    assert len(fake.calls) <= 9
    # slug order preserved within each board; probing stops at the first hit
    assert "patronusai" in fake.calls[0] and "greenhouse" in fake.calls[0]
    assert "patronus-ai/jobs" in fake.calls[1]
    assert fake.calls[-1] == "https://api.ashbyhq.com/posting-api/job-board/patronus-ai"
    assert signals and all(s["board"] == "ashby" for s in signals)


async def test_scan_no_board_found_returns_empty():
    fake = _router([])  # everything 404s
    with patch("scrapers.job_boards._get_json", fake):
        signals = await scan_company_jobs("Nonexistent Co", "nonexistent.example")
    assert signals == []
    assert len(fake.calls) <= 9


# ---------------------------------------------------------------- gtm_hiring_summary

async def test_gtm_hiring_summary_greenhouse():
    fake = _router(
        [("https://boards-api.greenhouse.io/v1/boards/vercel/jobs",
          (200, _load("job_boards_greenhouse_vercel.json")))]
    )
    with patch("scrapers.job_boards._get_json", fake):
        summary = await gtm_hiring_summary("Vercel", "vercel.com")
    assert summary["board"] == "greenhouse"
    assert summary["slug"] == "vercel"
    assert summary["total_jobs"] == 66  # from meta.total, not len(jobs)
    assert summary["gtm_jobs"] == 2
    assert "Account Executive, Majors" in summary["roles"]
    assert summary["careers_url"] == "https://boards.greenhouse.io/vercel"


async def test_gtm_hiring_summary_ashby():
    fake = _router(
        [
            ("https://boards-api.greenhouse.io/", (404, None)),
            ("https://api.lever.co/", (200, [])),
            ("https://api.ashbyhq.com/posting-api/job-board/linear",
             (200, _load("job_boards_ashby_linear.json"))),
        ]
    )
    with patch("scrapers.job_boards._get_json", fake):
        summary = await gtm_hiring_summary("Linear", "linear.app")
    assert summary["board"] == "ashby"
    assert summary["total_jobs"] == 4
    assert summary["gtm_jobs"] == 3
    assert set(summary["roles"]) == {
        "Account Executive, Startups",
        "Customer Success Manager",
        "Product Marketing Manager",
    }
    assert summary["careers_url"] == "https://jobs.ashbyhq.com/linear"


async def test_gtm_hiring_summary_no_board():
    fake = _router([])
    with patch("scrapers.job_boards._get_json", fake):
        summary = await gtm_hiring_summary("Nonexistent Co")
    assert summary == {}
