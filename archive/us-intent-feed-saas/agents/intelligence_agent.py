"""Intelligence Agent.

Analyzes a company holistically given its signals and profile.
Identifies likely needs, best contact titles, and timing context.
Uses Claude Sonnet 4.6 for reasoning.
"""

from __future__ import annotations

from agents.base_agent import BaseAgent
from llm.claude_router import ClaudeRouter
from models.company import CompanyProfile
from models.signal import Opportunity, Signal

_INTEL_SYSTEM = (
    "You are a senior B2B sales intelligence analyst. "
    "Your analysis must be specific, evidence-based, and immediately actionable. "
    "Never give generic advice. Always tie recommendations directly to the signals."
)

_INTEL_PROMPT = """Analyze this company based on its buying-intent signals and recommend
the best sales approach for an AI automation agency.

Company: {company_name}
Industry: {industry}
Size: {employee_count} employees
Tech Stack: {tech_stack}

Detected Signals:
{signals_text}

Provide:
1. likely_needs: 3 specific AI/automation services this company probably needs RIGHT NOW
   (e.g., "AI-powered sales sequence automation" not "automation tools")
2. decision_maker_titles: 2-3 exact job titles who would approve this purchase
3. timing_note: One sentence on why contacting them THIS WEEK (not next month) matters
4. approach_angle: The single most compelling opening angle for cold outreach

Return JSON only:
{{
  "likely_needs": ["...", "...", "..."],
  "decision_maker_titles": ["...", "..."],
  "timing_note": "...",
  "approach_angle": "..."
}}"""


class IntelligenceAgent(BaseAgent[tuple[CompanyProfile, list[Signal]], dict]):
    """Enrich an opportunity with actionable intelligence."""

    name = "intelligence"

    def __init__(self, llm: ClaudeRouter | None = None) -> None:
        super().__init__()
        self._llm = llm or ClaudeRouter()

    async def run(self, payload: tuple[CompanyProfile, list[Signal]]) -> dict:
        company, signals = payload
        self._log_start(company.name)

        signals_text = "\n".join(
            f"- [{s.signal_type.value.upper()}] {s.detail} (confidence: {s.confidence:.0%})"
            for s in signals[:8]
        )
        prompt = _INTEL_PROMPT.format(
            company_name=company.name,
            industry=company.industry or "Unknown",
            employee_count=company.employee_count or "Unknown",
            tech_stack=", ".join(company.tech_stack[:8]) if company.tech_stack else "Unknown",
            signals_text=signals_text,
        )
        result = await self._llm.analyze(prompt, _INTEL_SYSTEM)
        self._log_done(company.name)
        return result
