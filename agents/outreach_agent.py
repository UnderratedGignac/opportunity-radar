"""Outreach Agent.

Generates personalized cold outreach copy for each opportunity.
Adapted from auto-apply-agent's cover letter tailoring pattern.
Uses Claude Sonnet 4.6 for human-quality copy.
"""

from __future__ import annotations

from agents.base_agent import BaseAgent
from llm.claude_router import ClaudeRouter
from models.signal import Opportunity, OutreachPackage

_OUTREACH_SYSTEM = (
    "You are a B2B copywriter who specializes in cold outreach for AI automation agencies. "
    "Write copy that sounds human, references the SPECIFIC signal (not generic), "
    "and creates urgency through timing — not hype. "
    "Never use: synergy, leverage, revolutionary, game-changer, cutting-edge. "
    "Keep email body under 110 words. LinkedIn under 290 chars."
)

_OUTREACH_PROMPT = """Write personalized cold outreach for this opportunity.

AGENCY (your client):
Name: {agency_name}
Specialty: {agency_specialty}

TARGET OPPORTUNITY:
Company: {company_name}
Score: {score}/100
Top signals:
{signals_text}
Likely needs: {likely_needs}
Best contact title: {decision_maker}
Why now: {timing_rationale}

Write all four formats. The opening MUST reference the specific signal (e.g., "I saw you raised $8M last week").

Return JSON:
{{
  "email_subject": "under 50 chars, no clickbait",
  "email_body": "under 110 words, open with signal, end with soft CTA",
  "linkedin_message": "under 290 chars",
  "call_opener": "one sentence that proves research was done"
}}"""


class OutreachAgent(BaseAgent[tuple[Opportunity, dict], OutreachPackage]):
    """Generate personalized outreach copy for an opportunity."""

    name = "outreach"

    def __init__(
        self,
        llm: ClaudeRouter | None = None,
        agency_name: str = "Your Agency",
        agency_specialty: str = "AI automation for B2B companies",
    ) -> None:
        super().__init__()
        self._llm = llm or ClaudeRouter()
        self._agency_name = agency_name
        self._agency_specialty = agency_specialty

    async def run(self, payload: tuple[Opportunity, dict]) -> OutreachPackage:
        opportunity, intel = payload
        self._log_start(opportunity.company_name)

        top_signals = [s.signal.detail for s in opportunity.signals[:3]]
        signals_text = "\n".join(f"- {s}" for s in top_signals)
        likely_needs = intel.get("likely_needs", opportunity.likely_needs)
        decision_maker = (
            intel.get("decision_maker_titles", ["CEO"])[0]
            if intel.get("decision_maker_titles")
            else "CEO"
        )

        prompt = _OUTREACH_PROMPT.format(
            agency_name=self._agency_name,
            agency_specialty=self._agency_specialty,
            company_name=opportunity.company_name,
            score=opportunity.opportunity_score,
            signals_text=signals_text,
            likely_needs=", ".join(likely_needs[:3]) if likely_needs else "AI automation",
            decision_maker=decision_maker,
            timing_rationale=opportunity.timing_rationale,
        )

        copy = await self._llm.analyze(prompt, _OUTREACH_SYSTEM)

        pkg = OutreachPackage(
            opportunity=opportunity,
            email_subject=copy.get("email_subject", ""),
            email_body=copy.get("email_body", ""),
            linkedin_message=copy.get("linkedin_message", ""),
            call_opener=copy.get("call_opener", ""),
        )
        self._log_done(opportunity.company_name)
        return pkg
