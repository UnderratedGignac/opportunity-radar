"""Signal Processing Pipeline.

Adapted from auto-apply-agent's ApplicationStateMachine. Replaces:
  DISCOVER_JOB   → COLLECT_SIGNALS
  FILL_FORM      → ANALYZE_COMPANY
  SUBMIT         → SCORE_OPPORTUNITY
  VERIFY         → GENERATE_OUTREACH

Each company runs through all four stages sequentially.
The pipeline is async and processes multiple companies concurrently (up to concurrency limit).
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum

from agents.intelligence_agent import IntelligenceAgent
from agents.outreach_agent import OutreachAgent
from agents.scoring_agent import ScoringAgent
from agents.signal_collection_agent import SignalCollectionAgent
from core.event_bus import EventBus
from models.company import CompanyProfile
from models.signal import Contact, Opportunity, OutreachPackage
from scrapers.contacts import get_contacts

logger = logging.getLogger("radar.pipeline")


class PipelineState(Enum):
    COLLECT_SIGNALS = "collect_signals"
    ANALYZE_COMPANY = "analyze_company"
    SCORE_OPPORTUNITY = "score_opportunity"
    GENERATE_OUTREACH = "generate_outreach"
    COMPLETE = "complete"
    FAILED = "failed"


class CompanyPipeline:
    """Run a single company through the full signal → opportunity pipeline."""

    def __init__(
        self,
        collector: SignalCollectionAgent,
        intelligence: IntelligenceAgent,
        scorer: ScoringAgent,
        outreach: OutreachAgent,
        event_bus: EventBus | None = None,
    ) -> None:
        self._collector = collector
        self._intelligence = intelligence
        self._scorer = scorer
        self._outreach = outreach
        self._bus = event_bus
        self.state = PipelineState.COLLECT_SIGNALS

    async def run(self, company: CompanyProfile) -> OutreachPackage | None:
        logger.info("Pipeline start: %s", company.name)
        try:
            self.state = PipelineState.COLLECT_SIGNALS
            signals = await self._collector.run([company.domain])
            if not signals:
                logger.info("No signals found for %s — skipping", company.name)
                self.state = PipelineState.COMPLETE
                return None

            self.state = PipelineState.ANALYZE_COMPANY
            intel = await self._intelligence.run((company, signals))

            self.state = PipelineState.SCORE_OPPORTUNITY
            opportunity = await self._scorer.run((company, signals))
            opportunity.likely_needs = intel.get("likely_needs", [])
            opportunity.decision_maker_titles = intel.get("decision_maker_titles", [])

            self.state = PipelineState.GENERATE_OUTREACH
            raw_contacts = await get_contacts(company.domain, company.name)
            contacts = []
            for c in raw_contacts:
                contacts.append(Contact(
                    first_name=c.get("first_name"),
                    last_name=c.get("last_name"),
                    title=c.get("title", ""),
                    email=c.get("email"),
                    linkedin_url=c.get("linkedin_url"),
                    company_domain=company.domain,
                    source=c.get("source", "pattern_inference"),
                ))
            package = await self._outreach.run((opportunity, intel))
            package.contacts = contacts

            self.state = PipelineState.COMPLETE
            if self._bus:
                await self._bus.publish("opportunity_ready", {
                    "company": company.name,
                    "score": opportunity.opportunity_score,
                })
            logger.info("Pipeline complete: %s score=%d", company.name, opportunity.opportunity_score)
            return package

        except Exception as e:
            self.state = PipelineState.FAILED
            logger.error("Pipeline failed for %s: %s", company.name, e)
            return None


class RadarOrchestrator:
    """Process a batch of companies with bounded concurrency."""

    def __init__(self, pipeline: CompanyPipeline, concurrency: int = 5) -> None:
        self._pipeline = pipeline
        self._concurrency = concurrency

    async def run_batch(self, companies: list[CompanyProfile]) -> list[OutreachPackage]:
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _bounded(company: CompanyProfile) -> OutreachPackage | None:
            async with semaphore:
                return await self._pipeline.run(company)

        results = await asyncio.gather(*[_bounded(c) for c in companies], return_exceptions=True)
        packages = [r for r in results if isinstance(r, OutreachPackage)]
        logger.info(
            "Batch complete: %d/%d companies produced opportunities",
            len(packages), len(companies),
        )
        return packages
