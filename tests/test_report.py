"""Offline tests for report.py — the weekly Buying-Intent Report generator.

No network, no imports of the other scraper modules. Fixture facts are
modelled on a REAL payload captured 2026-07-08 from the live Google News RSS
funding feed (see _REAL_HEADLINE below).
"""

from __future__ import annotations

import report

# Trimmed from the live endpoint on 2026-07-08:
# curl "https://news.google.com/rss/search?q=%22raised%22%20%22Series%20A%22..."
_REAL_HEADLINE = (
    "Oratomic Raises $300 Million Series A - The Quantum Insider"
)
_REAL_PUBDATE = "Tue, 07 Jul 2026 17:54:48 GMT"
_REAL_LINK = "https://news.google.com/rss/articles/CBMihAFBVV95cUxQ?oc=5"


def _funding_event(**overrides) -> dict:
    ev = {
        "company": "Oratomic",
        "amount_millions": 300.0,
        "round_type": "series a",
        "signal_type": "funding",
        "detail": "Raised $300M Series A",
        "source_url": _REAL_LINK,
        "source_name": "The Quantum Insider",
        "published_at": _REAL_PUBDATE,
        "confidence": 0.85,
    }
    ev.update(overrides)
    return ev


def _hiring_post(**overrides) -> dict:
    post = {
        "company": "Oratomic",
        "roles": ["Account Executive", "SDR"],
        "location": "NYC",
        "remote": True,
        "funding_stage": "series a",
        "has_gtm_roles": True,
        "snippet": "Oratomic | AE, SDR | NYC/remote",
        "signal_type": "hiring",
        "detail": "Hiring Account Executive, SDR (HN Who is hiring)",
        "source_url": "https://news.ycombinator.com/item?id=44001234",
        "confidence": 0.7,
    }
    post.update(overrides)
    return post


# ---------------------------------------------------------------- merge

def test_merge_companies_groups_by_normalized_name():
    funding = [
        _funding_event(company="Oratomic, Inc."),
        _funding_event(company="Beta Robotics", amount_millions=8.0),
    ]
    hiring = [_hiring_post(company="oratomic inc")]

    candidates = report.merge_companies(funding, hiring)

    assert len(candidates) == 2
    by_name = {c["name"]: c for c in candidates}
    assert "Oratomic, Inc." in by_name  # first-seen casing wins
    ora = by_name["Oratomic, Inc."]
    assert len(ora["funding"]) == 1
    assert len(ora["hiring"]) == 1
    assert ora["domain"] is None
    beta = by_name["Beta Robotics"]
    assert len(beta["funding"]) == 1
    assert beta["hiring"] == []


def test_merge_companies_drops_blank_names_and_keeps_orphan_hiring():
    funding = [_funding_event(company="")]
    hiring = [_hiring_post(company="SoloHire")]

    candidates = report.merge_companies(funding, hiring)

    assert len(candidates) == 1
    assert candidates[0]["name"] == "SoloHire"
    assert candidates[0]["funding"] == []
    assert len(candidates[0]["hiring"]) == 1


def test_normalize_company_strips_legal_suffixes():
    assert report.normalize_company("Oratomic, Inc.") == report.normalize_company(
        "oratomic inc"
    )
    assert report.normalize_company("Beta Robotics Ltd") == report.normalize_company(
        "beta robotics"
    )
    # distinct companies must stay distinct
    assert report.normalize_company("Oratomic") != report.normalize_company(
        "Beta Robotics"
    )


# ---------------------------------------------------------------- scoring
#
# Weighted multi-signal model. Funding: +30 base, +10 amount sweet spot
# ($3-100M — enough to spend, not enterprise-locked), +10 seed/series a
# (+5 series b). Job board: +15 any GTM role, +5 at 3+, +10 exec GTM role,
# +5 high-intent role (AE/SDR/RevOps). HN: +10, +5 with GTM roles.
# Multi-signal +15. Negative news (layoffs/freeze) -30. Clamp 0-100.

def test_score_funding_only_base():
    cand = {"name": "A", "funding": [_funding_event(amount_millions=2.0, round_type="unknown")], "hiring": []}
    assert report.score_company(cand) == 30  # tiny raise, unknown round: base only


def test_score_funding_amount_and_round_bonuses():
    sweet = {
        "name": "A",
        "funding": [_funding_event(amount_millions=15.0, round_type="series a")],
        "hiring": [],
    }
    assert report.score_company(sweet) == 50  # 30 + 10 amount + 10 round

    seed = {
        "name": "B",
        "funding": [_funding_event(amount_millions=3.0, round_type="seed")],
        "hiring": [],
    }
    assert report.score_company(seed) == 50  # $3M is inside the sweet spot

    mega = {
        "name": "C",
        "funding": [_funding_event(amount_millions=300.0, round_type="series a")],
        "hiring": [],
    }
    # big-round discount: $100M+ companies usually have preferred vendors
    assert report.score_company(mega) == 40  # 30 + 0 amount + 10 round

    series_b = {
        "name": "D",
        "funding": [_funding_event(amount_millions=40.0, round_type="series b")],
        "hiring": [],
    }
    assert report.score_company(series_b) == 45  # 30 + 10 amount + 5 series b


def test_score_hn_hiring_only():
    plain = {"name": "C", "funding": [], "hiring": [_hiring_post(has_gtm_roles=False)]}
    assert report.score_company(plain) == 10
    gtm = {"name": "C", "funding": [], "hiring": [_hiring_post(has_gtm_roles=True)]}
    assert report.score_company(gtm) == 15


def test_score_job_board_role_granularity():
    one_generic = {"name": "D", "funding": [], "hiring": [],
                   "job_board": {"gtm_jobs": 1, "roles": ["Customer Success Manager"]}}
    assert report.score_company(one_generic) == 15

    many = {"name": "D", "funding": [], "hiring": [],
            "job_board": {"gtm_jobs": 4, "roles": ["Customer Success Manager"]}}
    assert report.score_company(many) == 20  # +5 at 3+ openings

    high_intent = {"name": "D", "funding": [], "hiring": [],
                   "job_board": {"gtm_jobs": 2, "roles": ["Account Executive"]}}
    assert report.score_company(high_intent) == 20  # +5 AE/SDR/RevOps

    exec_role = {"name": "D", "funding": [], "hiring": [],
                 "job_board": {"gtm_jobs": 1, "roles": ["Head of Sales"]}}
    assert report.score_company(exec_role) == 25  # +10 revenue-leadership hire


def test_score_multi_signal_bonus_and_clamp():
    both = {
        "name": "E",
        "funding": [_funding_event(amount_millions=2.0, round_type="unknown")],
        "hiring": [_hiring_post(has_gtm_roles=False)],
    }
    assert report.score_company(both) == 55  # 30 + 10 + 15 multi-signal

    maxed = {
        "name": "F",
        "funding": [_funding_event(amount_millions=30.0, round_type="series a")],
        "hiring": [_hiring_post(has_gtm_roles=True)],
        "job_board": {"gtm_jobs": 4, "roles": ["Head of Sales", "Account Executive"]},
    }
    # 30+10+10 + 15+5+10+5 + 10+5 + 15 = 115 -> clamped
    assert report.score_company(maxed) == 100

    assert report.score_company({"name": "G", "funding": [], "hiring": []}) == 0


def test_rank_candidates_breaks_ties_by_amount_not_alphabet():
    small = {"name": "Aardvark", "funding": [_funding_event(company="Aardvark", amount_millions=4.0, round_type="seed")], "hiring": []}
    big = {"name": "Zenith", "funding": [_funding_event(company="Zenith", amount_millions=60.0, round_type="seed")], "hiring": []}
    for c in (small, big):
        c["score"] = report.score_company(c)
    assert small["score"] == big["score"]  # both in the sweet spot
    ranked = report.rank_candidates([small, big])
    # bigger raise = more budget = ranks first, despite alphabet
    assert [c["name"] for c in ranked] == ["Zenith", "Aardvark"]


def test_score_negative_news_penalty():
    cand = {
        "name": "H",
        "funding": [_funding_event(amount_millions=15.0, round_type="series a")],
        "hiring": [],
        "negative_news": [{"detail": "H announces layoffs of 20% of staff", "negative": True}],
    }
    assert report.score_company(cand) == 20  # 50 - 30: layoffs kill the window


# ---------------------------------------------------------------- likely_need

def test_likely_need_exec_gtm():
    cand = {"name": "A", "funding": [], "hiring": [],
            "job_board": {"gtm_jobs": 1, "roles": ["Head of Sales"]}}
    need = report.likely_need(cand)
    assert "revenue leadership" in need.lower()


def test_likely_need_outbound_scaling():
    cand = {"name": "A", "funding": [], "hiring": [],
            "job_board": {"gtm_jobs": 2, "roles": ["Account Executive", "SDR"]}}
    need = report.likely_need(cand)
    assert "outbound" in need.lower() or "pipeline" in need.lower()


def test_likely_need_funded_no_hiring():
    cand = {"name": "A", "funding": [_funding_event()], "hiring": []}
    need = report.likely_need(cand)
    assert "budget" in need.lower()


def test_likely_need_hn_only():
    cand = {"name": "A", "funding": [], "hiring": [_hiring_post()]}
    assert report.likely_need(cand)  # non-empty for every branch


# ---------------------------------------------------------------- why_now / opener

def test_why_now_funding_plus_gtm_hiring_mentions_both_facts():
    cand = {
        "name": "Oratomic",
        "funding": [_funding_event()],
        "hiring": [],
        "job_board": {"gtm_jobs": 4, "roles": ["Account Executive"], "careers_url": "https://boards.greenhouse.io/oratomic"},
    }
    text = report.why_now(cand)
    assert "$300M" in text
    assert "Series A" in text
    assert "Jul 7" in text  # parsed from the real RFC-822 pubDate
    assert "4 open GTM roles" in text


def test_why_now_funding_only_and_hiring_only():
    funded = {"name": "A", "funding": [_funding_event(amount_millions=15.0)], "hiring": []}
    text = report.why_now(funded)
    assert "$15M" in text
    assert "budget" in text.lower()

    hiring_only = {"name": "B", "funding": [], "hiring": [_hiring_post()]}
    text2 = report.why_now(hiring_only)
    assert "Account Executive" in text2
    assert "pipeline" in text2.lower()


def test_suggested_opener_references_actual_signals():
    cand = {
        "name": "Oratomic",
        "funding": [_funding_event()],
        "hiring": [],
        "job_board": {"gtm_jobs": 2, "roles": ["Account Executive"]},
    }
    opener = report.suggested_opener(cand)
    assert "$300M" in opener
    assert "Account Executive" in opener

    hire_only = {"name": "SoloHire", "funding": [], "hiring": [_hiring_post(company="SoloHire")]}
    opener2 = report.suggested_opener(hire_only)
    assert "SoloHire" in opener2
    assert "Account Executive" in opener2


# ---------------------------------------------------------------- rendering

def _entries() -> list[dict]:
    return [
        {
            "rank": 1,
            "name": "Oratomic",
            "domain": None,
            "score": 100,
            "funding": [_funding_event()],
            "hiring": [_hiring_post()],
            "job_board": {
                "board": "greenhouse",
                "slug": "oratomic",
                "total_jobs": 12,
                "gtm_jobs": 4,
                "roles": ["Account Executive", "Head of Growth"],
                "careers_url": "https://boards.greenhouse.io/oratomic",
            },
        },
        {
            "rank": 2,
            "name": "Beta Robotics",
            "domain": None,
            "score": 45,
            "funding": [_funding_event(company="Beta Robotics", amount_millions=2.0, round_type="unknown", detail="Raised $2M", source_url="https://example.com/beta")],
            "hiring": [],
        },
    ]


def test_render_markdown_contains_required_sections():
    md = report.render_markdown(_entries(), generated_on="2026-07-08")

    assert "AI Opportunity Radar — Weekly Buying-Intent Report" in md
    assert "2026-07-08" in md
    assert "## 1. Oratomic — 100/100" in md
    assert "## 2. Beta Robotics — 45/100" in md
    assert _REAL_LINK in md  # source link preserved
    assert "https://boards.greenhouse.io/oratomic" in md  # careers link
    assert "**Why now:**" in md
    assert "**Likely need:**" in md
    assert "**Who to contact:**" in md
    assert "**Suggested opener:**" in md
    # footer: methodology + attribution
    assert "SEC EDGAR" in md
    assert "Hacker News" in md
    assert "Generated by AI Opportunity Radar" in md


def test_render_csv_rows_columns_and_values():
    rows = report.render_csv_rows(_entries())

    assert len(rows) == 2
    expected_cols = [
        "Company", "Score", "Signals", "FundingDetail", "GTMOpenRoles",
        "LikelyNeed", "Domain", "SourceLinks", "SuggestedContactTitle",
        "SuggestedOpener",
    ]
    for row in rows:
        assert list(row.keys()) == expected_cols

    ora = rows[0]
    assert ora["Company"] == "Oratomic"
    assert ora["Score"] == 100
    assert "funding" in ora["Signals"]
    assert ora["GTMOpenRoles"] == 4
    assert ora["LikelyNeed"]  # non-empty fit line
    assert _REAL_LINK in ora["SourceLinks"]
    assert ora["SuggestedOpener"]  # non-empty

    beta = rows[1]
    assert beta["GTMOpenRoles"] == 0
    assert beta["FundingDetail"] == "Raised $2M"


def test_write_report_creates_both_files(tmp_path):
    md_path, csv_path = report.write_report(_entries(), str(tmp_path / "samples"), generated_on="2026-07-08")

    assert md_path.name == "intent_report_2026-07-08.md"
    assert csv_path.name == "intent_report_2026-07-08.csv"
    assert md_path.exists() and csv_path.exists()
    md = md_path.read_text(encoding="utf-8")
    assert "Oratomic" in md
    csv_text = csv_path.read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("Company,Score,Signals")
