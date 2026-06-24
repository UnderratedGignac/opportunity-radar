"""Learning feedback loop integration tests — TDD RED phase.

Tests that the LearningAgent's weight updates actually reach the ScoringAgent.

Run: pytest tests/test_learning_loop.py -v
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.company import CompanyProfile
from models.signal import Signal, SignalType
from agents.scoring_agent import ScoringAgent


def _make_signal(detail: str, days_old: int = 2) -> Signal:
    return Signal(
        company_domain="acme.com",
        signal_type=SignalType.FUNDING,
        detail=detail,
        detected_at=datetime.now(timezone.utc) - timedelta(days=days_old),
        confidence=0.9,
    )


def _make_company() -> CompanyProfile:
    return CompanyProfile(name="Acme", domain="acme.com", industry="saas", employee_count=50, business_model="b2b")


# ── DB weight loading ─────────────────────────────────────────────────────────

def test_scoring_agent_has_load_db_weights_classmethod():
    """ScoringAgent must expose a classmethod to build a weights dict from DB rows."""
    assert hasattr(ScoringAgent, "weights_from_db_rows"), (
        "ScoringAgent.weights_from_db_rows() not found — LearningAgent cannot push updates to scoring"
    )


def test_weights_from_db_rows_converts_dot_notation():
    """weights_from_db_rows must convert 'funding.series_a' → weights['funding']['series a']."""
    db_rows = {
        "funding.series_a": 50.0,
        "exec_change.vp_sales": 40.0,
        "hiring.sdr": 30.0,
    }
    weights = ScoringAgent.weights_from_db_rows(db_rows)

    assert weights["funding"]["series a"] == 50.0, f"Expected 50.0, got {weights.get('funding', {}).get('series a')}"
    assert weights["exec_change"]["vp sales"] == 40.0
    assert weights["hiring"]["sdr"] == 30.0


def test_scoring_uses_db_weights_when_loaded():
    """ScoringAgent initialized with DB-derived weights must use them for scoring."""
    mock_llm = AsyncMock()
    mock_llm.analyze.return_value = {"rationale": "ok"}

    # DB says series_a weight = 99 (artificially high to detect usage)
    db_rows = {"funding.series_a": 99.0}
    weights = ScoringAgent.weights_from_db_rows(db_rows)
    agent_db = ScoringAgent(llm=mock_llm, weights=weights)

    agent_default = ScoringAgent(llm=mock_llm)

    company = _make_company()
    signals = [_make_signal("raised $10M Series A", days_old=1)]

    score_db = asyncio.run(agent_db.run((company, signals))).opportunity_score
    score_default = asyncio.run(agent_default.run((company, signals))).opportunity_score

    assert score_db > score_default, (
        f"DB-loaded weight=99 should produce higher score than default=35. "
        f"Got db={score_db} default={score_default}"
    )
