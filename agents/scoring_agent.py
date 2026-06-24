"""Scoring Agent.

Computes the opportunity score for a company given its signals and profile.
Uses the weighted formula from the business blueprint, with Claude Sonnet
for rationale generation.

Score = Σ(signal_weight × recency_multiplier) × company_fit_multiplier × confidence
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from agents.base_agent import BaseAgent
from llm.claude_router import ClaudeRouter
from models.company import CompanyProfile
from models.signal import Opportunity, Signal, ScoredSignal

# Base weights per signal type + detail keywords
_SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    "funding": {
        "series d": 38, "series c": 40, "series a": 35, "series b": 32,
        "ipo": 32, "went public": 30, "acquisition": 30, "acquired": 28,
        "merger": 25, "strategic investment": 20,
        "seed": 22, "pre-seed": 18, "pre_seed": 10,
        "raised": 25, "funding": 20, "default": 20,
    },
    "exec_change": {
        "vp sales": 35, "cro": 35, "chief revenue": 35,
        "cmo": 30, "vp marketing": 30, "chief marketing": 30,
        "head of sales": 30, "head of revenue": 30, "head of growth": 20,
        "coo": 25, "vp operations": 25, "chief operating": 25,
        "chief of staff": 14, "ceo": 20, "default": 18,
    },
    "hiring": {
        "sdr": 28, "sales development": 28, "account executive": 25,
        "demand generation": 16, "customer success manager": 18,
        "marketing manager": 22, "revenue operations": 18,
        "customer success": 20, "support": 12, "default": 15,
    },
    "tech_change": {
        "salesforce": 28, "hubspot": 22, "marketo": 22, "pardot": 22,
        "zapier": 20, "make": 18, "automation": 20, "crm": 25,
        "default": 15,
    },
    "website_change": {
        "enterprise": 14, "pricing updated": 13, "pricing": 13,
        "schedule a demo": 12, "we're hiring": 10, "we are hiring": 10,
        "product": 18, "office": 12, "default": 8,
    },
    "news": {"default": 10},
}

_RECENCY_CURVE = [
    (3, 1.0),
    (7, 0.95),
    (14, 0.80),
    (30, 0.60),
    (60, 0.35),
    (999, 0.15),
]

_SCORE_SYSTEM = (
    "You are a B2B sales intelligence scoring analyst. "
    "Write concise, specific, evidence-based rationale. No fluff."
)

_SCORE_PROMPT = """A company shows the following buying-intent signals. Write a one-sentence
rationale explaining why this opportunity scores {score}/100 and why NOW is the right time.

Company: {company}
Signals:
{signals_text}

Return JSON: {{"rationale": "one sentence"}}"""


class ScoringAgent(BaseAgent[tuple[CompanyProfile, list[Signal]], Opportunity]):
    """Score a company's buying intent and build the full opportunity card."""

    name = "scoring"

    def __init__(
        self,
        llm: ClaudeRouter | None = None,
        weights: dict[str, dict[str, float]] | None = None,
    ) -> None:
        super().__init__()
        self._llm = llm or ClaudeRouter()
        self._weights = weights if weights is not None else _SIGNAL_WEIGHTS

    @staticmethod
    def weights_from_db_rows(db_rows: dict[str, float]) -> dict[str, dict[str, float]]:
        """Convert DB signal_weights rows (dot-notation) into the scoring weights dict format.

        DB format:   {"funding.series_a": 35.0, "exec_change.vp_sales": 35.0}
        Scoring fmt: {"funding": {"series a": 35.0, ...}, "exec_change": {"vp sales": 35.0, ...}}

        Merges over a deep copy of the hardcoded defaults so uncalibrated signals keep their baseline.
        """
        import copy
        merged = copy.deepcopy(_SIGNAL_WEIGHTS)
        for key, weight in db_rows.items():
            if "." not in key:
                continue
            signal_type, keyword_raw = key.split(".", 1)
            keyword = keyword_raw.replace("_", " ")
            if signal_type not in merged:
                merged[signal_type] = {"default": 10}
            merged[signal_type][keyword] = weight
        return merged

    async def run(self, payload: tuple[CompanyProfile, list[Signal]]) -> Opportunity:
        company, signals = payload
        self._log_start(f"{company.name} — {len(signals)} signals")

        scored = [self._score_signal(s) for s in signals]
        raw_total = sum(s.weighted_score for s in scored)
        fit_mult = company.fit_multiplier
        n_sources = len({s.signal.source_type for s in scored if s.signal.source_type})
        confidence = min(0.95, (n_sources / 3) * 0.90 + 0.10)

        # Source diversity bonus: 3+ source types boosts score 10%
        unique_sources = len({s.signal.source_type for s in scored if s.signal.source_type})
        diversity_mult = 1.1 if unique_sources >= 3 else 1.0

        raw_score = raw_total * fit_mult * confidence * diversity_mult
        # Normalize: 0.75 factor lets multi-signal companies reach 80+ while single signals stay below 30
        normalized = int(min(100, math.floor(raw_score * 0.75)))

        rationale = await self._get_rationale(company.name, signals, normalized)

        opp = Opportunity(
            company_name=company.name,
            company_domain=company.domain,
            opportunity_score=normalized,
            confidence_score=int(confidence * 100),
            signals=scored,
            score_breakdown=[
                {
                    "signal": s.signal.detail,
                    "type": s.signal.signal_type.value,
                    "base_weight": s.base_weight,
                    "recency_multiplier": s.recency_multiplier,
                    "weighted": round(s.weighted_score, 2),
                }
                for s in scored
            ],
            timing_rationale=rationale,
        )
        self._log_done(f"score={normalized} confidence={int(confidence*100)}%")
        return opp

    def _score_signal(self, signal: Signal) -> ScoredSignal:
        base = self._base_weight(signal)
        recency = self._recency_multiplier(signal.detected_at)
        return ScoredSignal(
            signal=signal,
            base_weight=base,
            recency_multiplier=recency,
            weighted_score=base * recency * signal.confidence,
        )

    def _base_weight(self, signal: Signal) -> float:
        type_weights = self._weights.get(signal.signal_type.value, {"default": 10})
        detail_lower = signal.detail.lower()
        for keyword, weight in type_weights.items():
            if keyword != "default" and keyword in detail_lower:
                return float(weight)
        return float(type_weights.get("default", 10))

    def _recency_multiplier(self, detected_at: datetime) -> float:
        now = datetime.now(timezone.utc)
        if detected_at.tzinfo is None:
            detected_at = detected_at.replace(tzinfo=timezone.utc)
        age_days = (now - detected_at).days
        for threshold, mult in _RECENCY_CURVE:
            if age_days <= threshold:
                return mult
        return 0.10

    async def _get_rationale(self, company: str, signals: list[Signal], score: int) -> str:
        signals_text = "\n".join(f"- {s.signal_type.value}: {s.detail}" for s in signals[:5])
        prompt = _SCORE_PROMPT.format(company=company, score=score, signals_text=signals_text)
        result = await self._llm.analyze(prompt, _SCORE_SYSTEM)
        return result.get("rationale", f"Score {score}/100 based on {len(signals)} detected signals.")
