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

def test_score_funding_only_base():
    cand = {"name": "A", "funding": [_funding_event(amount_millions=2.0, round_type="unknown")], "hiring": []}
    assert report.score_company(cand) == 45


def test_score_funding_amount_and_sweet_spot_round_bonuses():
    cand = {
        "name": "A",
        "funding": [_funding_event(amount_millions=15.0, round_type="series a")],
        "hiring": [],
    }
    # 45 base + 5 (>= $5M) + 5 (seed/series a)
    assert report.score_company(cand) == 55

    seed = {
        "name": "B",
        "funding": [_funding_event(amount_millions=3.0, round_type="seed")],
        "hiring": [],
    }
    # 45 base + 5 round bonus only (amount < 5M)
    assert report.score_company(seed) == 50


def test_score_hn_hiring_only():
    plain = {"name": "C", "funding": [], "hiring": [_hiring_post(has_gtm_roles=False)]}
    assert report.score_company(plain) == 15
    gtm = {"name": "C", "funding": [], "hiring": [_hiring_post(has_gtm_roles=True)]}
    assert report.score_company(gtm) == 20


def test_score_job_board_gtm_only_capped_at_30():
    cand = {"name": "D", "funding": [], "hiring": [], "job_board": {"gtm_jobs": 9, "total_jobs": 40}}
    assert report.score_company(cand) == 30


def test_score_multi_signal_bonus_and_clamp():
    both = {
        "name": "E",
        "funding": [_funding_event(amount_millions=2.0, round_type="unknown")],
        "hiring": [_hiring_post(has_gtm_roles=False)],
    }
    # 45 + 15 + 10 multi-signal
    assert report.score_company(both) == 70

    maxed = {
        "name": "F",
        "funding": [_funding_event(amount_millions=300.0, round_type="series a")],
        "hiring": [_hiring_post(has_gtm_roles=True)],
        "job_board": {"gtm_jobs": 4, "careers_url": "https://boards.greenhouse.io/oratomic"},
    }
    # 45+5+5+30+15+5+10 = 115 -> clamped
    assert report.score_company(maxed) == 100

    assert report.score_company({"name": "G", "funding": [], "hiring": []}) == 0


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
        "Domain", "SourceLinks", "SuggestedContactTitle", "SuggestedOpener",
    ]
    for row in rows:
        assert list(row.keys()) == expected_cols

    ora = rows[0]
    assert ora["Company"] == "Oratomic"
    assert ora["Score"] == 100
    assert "funding" in ora["Signals"]
    assert ora["GTMOpenRoles"] == 4
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
