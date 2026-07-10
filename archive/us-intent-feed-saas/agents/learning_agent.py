"""Learning Agent — runs weekly to recalibrate signal weights from outcome data.

Uses Claude Opus 4.8 (most capable) for pattern recognition across outcomes.
Requires human approval before weights are updated (safety gate).
"""

from __future__ import annotations

import json
import logging

from agents.base_agent import BaseAgent
from db.repositories.opportunities import get_feedback_for_learning, update_signal_weight
from llm.claude_router import ClaudeRouter, SONNET

logger = logging.getLogger("radar.agent.learning")

_LEARNING_SYSTEM = (
    "You are a machine learning analyst specializing in B2B sales signal calibration. "
    "Analyze outcome data to identify which signal patterns predict successful client conversions. "
    "Be conservative — only recommend weight changes backed by at least 5 data points. "
    "Return valid JSON only."
)

_LEARNING_PROMPT = """Analyze the following outcome data from an AI opportunity scoring system.
Each record shows which signals were present when a sales opportunity was created,
and the outcome (converted, not_relevant, demo_booked, pursued).

Feedback data (last 30 days):
{feedback_json}

Current signal weights:
{weights_json}

Analyze:
1. Which signal types appear most frequently in 'converted' outcomes?
2. Which appear in 'not_relevant' outcomes?
3. Based on the data, what weight adjustments would improve prediction accuracy?
   (Only recommend changes with 5+ data points. Max change ±10 per signal.)

Return JSON:
{{
  "insights": "2-3 sentence summary of what the data reveals",
  "recommended_changes": [
    {{
      "signal_key": "...",
      "current_weight": 0,
      "recommended_weight": 0,
      "rationale": "...",
      "sample_size": 0
    }}
  ],
  "confidence": "low|medium|high"
}}"""


class LearningAgent(BaseAgent[int, dict]):
    """Analyze outcome data and recommend signal weight updates."""

    name = "learning"

    def __init__(self, llm: ClaudeRouter | None = None, auto_apply: bool = False) -> None:
        super().__init__()
        self._llm = llm or ClaudeRouter()
        self._auto_apply = auto_apply  # False = require human approval (safe default)

    async def run(self, days_lookback: int = 30) -> dict:
        self._log_start(f"analyzing last {days_lookback} days of feedback")

        feedback = await get_feedback_for_learning(days=days_lookback)
        if len(feedback) < 10:
            logger.info("Insufficient feedback data (%d records) — skipping", len(feedback))
            return {"status": "skipped", "reason": f"only {len(feedback)} records"}

        from db.repositories.opportunities import get_signal_weights
        current_weights = await get_signal_weights()

        prompt = _LEARNING_PROMPT.format(
            feedback_json=json.dumps(feedback[:100], indent=2, default=str),
            weights_json=json.dumps(current_weights, indent=2),
        )

        result = await self._llm.analyze(prompt, _LEARNING_SYSTEM)
        changes = result.get("recommended_changes", [])
        insights = result.get("insights", "")
        confidence = result.get("confidence", "low")

        logger.info(
            "Learning analysis complete: %d changes recommended (confidence=%s)",
            len(changes), confidence,
        )
        logger.info("Insights: %s", insights)

        if self._auto_apply and confidence in ("medium", "high"):
            applied = await self._apply_changes(changes)
            return {
                "status": "applied",
                "changes_applied": applied,
                "insights": insights,
                "confidence": confidence,
            }

        # Default: log recommendations, require manual review
        for change in changes:
            logger.warning(
                "WEIGHT RECOMMENDATION: %s → %.1f (was %.1f) | %s",
                change["signal_key"],
                change["recommended_weight"],
                change["current_weight"],
                change["rationale"],
            )

        return {
            "status": "pending_review",
            "recommended_changes": changes,
            "insights": insights,
            "confidence": confidence,
            "message": "Review recommendations above and call apply_changes() to commit.",
        }

    async def apply_changes(self, changes: list[dict]) -> int:
        return await self._apply_changes(changes)

    async def _apply_changes(self, changes: list[dict]) -> int:
        applied = 0
        for change in changes:
            signal_key = change.get("signal_key")
            new_weight = change.get("recommended_weight")
            rationale = change.get("rationale", "")
            sample_size = change.get("sample_size", 0)
            if not signal_key or new_weight is None:
                continue
            # Safety clamp: never allow weight below 1 or above 50
            new_weight = max(1.0, min(50.0, float(new_weight)))
            await update_signal_weight(signal_key, new_weight, rationale, sample_size)
            logger.info("Updated weight: %s = %.1f", signal_key, new_weight)
            applied += 1
        return applied
