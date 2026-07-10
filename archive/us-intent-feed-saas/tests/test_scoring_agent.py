"""Scoring agent tests — RED phase per TDD.

Run: pytest tests/test_scoring_agent.py -v
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest

from models.company import CompanyProfile
from models.signal import Signal, SignalType
from agents.scoring_agent import ScoringAgent


def _make_company(**kwargs) -> CompanyProfile:
    defaults = dict(name="Acme Corp", domain="acme.com", industry="saas", employee_count=50, business_model="b2b")
    return CompanyProfile(**{**defaults, **kwargs})


def _make_signal(signal_type=SignalType.FUNDING, detail="raised $10M Series A", days_old=2, confidence=0.9) -> Signal:
    return Signal(
        company_domain="acme.com",
        signal_type=signal_type,
        detail=detail,
        detected_at=datetime.now(timezone.utc) - timedelta(days=days_old),
        confidence=confidence,
    )


# ── C2: timezone-aware datetime must not crash scoring ────────────────────────

def test_signal_default_detected_at_is_timezone_aware():
    """Signal's DEFAULT detected_at (no explicit arg) must be timezone-aware or scoring crashes."""
    sig = Signal(
        company_domain="acme.com",
        signal_type=SignalType.FUNDING,
        detail="raised $10M",
    )
    assert sig.detected_at.tzinfo is not None, (
        "Signal.detected_at default uses datetime.utcnow() which is naive. "
        "ScoringAgent._recency_multiplier subtracts datetime.now(timezone.utc) — raises TypeError."
    )


def test_signal_detected_at_is_timezone_aware():
    """Signal.detected_at must be timezone-aware so recency math doesn't crash."""
    sig = _make_signal()
    assert sig.detected_at.tzinfo is not None, (
        "detected_at is naive — will crash with TypeError when subtracted from aware datetime"
    )


def test_scoring_agent_produces_nonzero_score():
    """ScoringAgent must return a score > 0 for a company with a fresh funding signal."""
    mock_llm = AsyncMock()
    mock_llm.analyze.return_value = {"rationale": "Strong signal"}
    agent = ScoringAgent(llm=mock_llm)
    company = _make_company()
    signals = [_make_signal(detail="raised $10M Series A", days_old=2)]

    result = asyncio.run(agent.run((company, signals)))

    assert result.opportunity_score > 0, (
        f"Score is {result.opportunity_score} — likely caused by timezone TypeError in recency calculation"
    )


def test_recency_multiplier_fresh_signal_returns_max():
    """A 1-day-old signal should get the maximum recency multiplier (1.0)."""
    agent = ScoringAgent(llm=AsyncMock())
    sig = _make_signal(days_old=1)
    mult = agent._recency_multiplier(sig.detected_at)
    assert mult == 1.0, f"Expected 1.0 for 1-day signal, got {mult}"


def test_recency_multiplier_old_signal_returns_low():
    """A 90-day-old signal should get the minimum recency multiplier."""
    agent = ScoringAgent(llm=AsyncMock())
    sig = _make_signal(days_old=90)
    mult = agent._recency_multiplier(sig.detected_at)
    assert mult <= 0.15, f"Expected ≤0.15 for 90-day signal, got {mult}"


# ── C1: learning weights must feed back into scoring ─────────────────────────

def test_scoring_agent_respects_custom_weights():
    """ScoringAgent must accept external weight overrides so LearningAgent can recalibrate it."""
    mock_llm = AsyncMock()
    mock_llm.analyze.return_value = {"rationale": "ok"}

    # Override funding.series_a weight to an extreme value so we can detect it was used
    custom_weights = {
        "funding": {"series a": 99, "default": 5},
    }
    agent = ScoringAgent(llm=mock_llm, weights=custom_weights)
    company = _make_company()
    signals = [_make_signal(detail="raised $10M Series A", days_old=1, confidence=1.0)]

    result_custom = asyncio.run(agent.run((company, signals)))

    default_agent = ScoringAgent(llm=mock_llm)
    result_default = asyncio.run(default_agent.run((company, signals)))

    assert result_custom.opportunity_score > result_default.opportunity_score, (
        "Custom weight=99 should produce higher score than default=35. "
        "ScoringAgent does not support injectable weights — learning loop is broken."
    )


# ── C4: circuit breaker must be per-instance, not class-wide ─────────────────

def test_circuit_breaker_per_instance():
    """Each ClaudeRouter instance must have its own failure counter."""
    from llm.claude_router import ClaudeRouter

    router_a = ClaudeRouter()
    router_b = ClaudeRouter()

    # Trip router_a's circuit by recording 5 failures
    for _ in range(ClaudeRouter._BREAK_AFTER):
        router_a._record_failure("simulated failure")

    # router_b must NOT be affected
    try:
        router_b._check_circuit()
    except RuntimeError as e:
        pytest.fail(
            f"router_b circuit tripped by router_a's failures — shared class state: {e}"
        )


# ── H1: model selection must differ by call type ─────────────────────────────

def test_analyze_uses_higher_tier_than_extract():
    """analyze() should use SONNET tier, extract() should use HAIKU tier — not both HAIKU."""
    from llm.claude_router import ClaudeRouter, HAIKU, SONNET

    assert HAIKU != SONNET, "HAIKU and SONNET must be different model IDs"

    calls = []

    async def fake_call(prompt, system, json_mode, model=None):
        calls.append(model)
        return "{}"

    router = ClaudeRouter()

    # Patch _call to capture model arg
    import llm.claude_router as cr
    original = cr._call

    async def patched_call(prompt, system, json_mode, model=HAIKU):
        calls.append(model)
        return "{}"

    cr._call = patched_call
    try:
        asyncio.run(router.extract("test", "system"))
        asyncio.run(router.analyze("test", "system"))
    finally:
        cr._call = original

    assert len(calls) == 2, f"Expected 2 calls, got {len(calls)}"
    extract_model, analyze_model = calls
    assert extract_model == HAIKU, f"extract() should use HAIKU, used {extract_model}"
    assert analyze_model == SONNET, f"analyze() should use SONNET, used {analyze_model}"


# ── H2: outreach agent must raise on empty LLM response ──────────────────────

def test_outreach_agent_raises_on_empty_llm():
    """OutreachAgent must not silently return blank copy when LLM fails."""
    from agents.outreach_agent import OutreachAgent
    from models.signal import Opportunity, ScoredSignal

    mock_llm = AsyncMock()
    mock_llm.analyze.return_value = {}  # LLM circuit open / parse failure

    agent = OutreachAgent(llm=mock_llm)

    opp = Opportunity(
        company_name="Acme",
        company_domain="acme.com",
        opportunity_score=75,
        confidence_score=80,
        signals=[],
        timing_rationale="Raised $10M",
    )

    with pytest.raises((RuntimeError, ValueError)):
        asyncio.run(agent.run((opp, {"likely_needs": ["automation"], "decision_maker_titles": ["CEO"]})))
