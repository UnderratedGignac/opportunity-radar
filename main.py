"""AI Opportunity Radar — main orchestrator.

Usage:
    # Scan a list of company domains
    python main.py --domains acme.com,growthstack.io,foobar.com

    # Scan from a file (one domain per line)
    python main.py --file domains.txt

    # Minimum score filter (default: 60)
    python main.py --domains acme.com --min-score 75

Output:
    JSON-formatted opportunity cards printed to stdout.
    High-confidence opportunities (score >= 80) logged at WARNING level
    so they stand out in any log aggregation system.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from agents.intelligence_agent import IntelligenceAgent
from agents.outreach_agent import OutreachAgent
from agents.scoring_agent import ScoringAgent
from agents.signal_collection_agent import SignalCollectionAgent
from config import settings
from core.event_bus import event_bus
from core.pipeline import CompanyPipeline, RadarOrchestrator
from llm.claude_router import ClaudeRouter
from models.company import CompanyProfile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("radar.main")


def _build_pipeline() -> CompanyPipeline:
    llm = ClaudeRouter()
    return CompanyPipeline(
        collector=SignalCollectionAgent(llm=llm, bing_api_key=settings.BING_API_KEY),
        intelligence=IntelligenceAgent(llm=llm),
        scorer=ScoringAgent(llm=llm),
        outreach=OutreachAgent(
            llm=llm,
            agency_name=settings.AGENCY_NAME,
            agency_specialty=settings.AGENCY_SPECIALTY,
        ),
        event_bus=event_bus,
    )


def _load_company(domain: str) -> CompanyProfile:
    """Minimal company profile — enrichment via Apollo/Clearbit in Month 2."""
    name = domain.split(".")[0].replace("-", " ").title()
    return CompanyProfile(name=name, domain=domain)


async def _run(domains: list[str], min_score: int) -> None:
    missing = settings.validate()
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    await event_bus.start()

    @event_bus.subscribe  # type: ignore[arg-type]
    async def _on_opportunity(data: dict) -> None:
        if data.get("score", 0) >= 80:
            logger.warning("HIGH-SCORE OPPORTUNITY: %s (score=%d)", data["company"], data["score"])

    companies = [_load_company(d) for d in domains]
    orchestrator = RadarOrchestrator(
        pipeline=_build_pipeline(),
        concurrency=settings.PIPELINE_CONCURRENCY,
    )

    packages = await orchestrator.run_batch(companies)
    filtered = [p for p in packages if p.opportunity.opportunity_score >= min_score]
    filtered.sort(key=lambda p: p.opportunity.opportunity_score, reverse=True)

    output = []
    for pkg in filtered:
        opp = pkg.opportunity
        output.append({
            "company": opp.company_name,
            "domain": opp.company_domain,
            "opportunity_score": opp.opportunity_score,
            "confidence_score": opp.confidence_score,
            "signals": [
                {"type": s.signal.signal_type.value, "detail": s.signal.detail}
                for s in opp.signals[:5]
            ],
            "likely_needs": opp.likely_needs,
            "decision_makers": opp.decision_maker_titles,
            "timing_rationale": opp.timing_rationale,
            "outreach": {
                "email_subject": pkg.email_subject,
                "email_body": pkg.email_body,
                "linkedin_message": pkg.linkedin_message,
                "call_opener": pkg.call_opener,
            },
        })

    print(json.dumps(output, indent=2, ensure_ascii=False))
    logger.info("Radar complete: %d opportunities above score %d", len(filtered), min_score)

    await event_bus.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Opportunity Radar")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--domains", help="Comma-separated company domains")
    group.add_argument("--file", help="File with one domain per line")
    parser.add_argument("--min-score", type=int, default=60, help="Minimum opportunity score")
    args = parser.parse_args()

    if args.domains:
        domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    else:
        with open(args.file) as f:
            domains = [line.strip() for line in f if line.strip()]

    if not domains:
        logger.error("No domains provided")
        sys.exit(1)

    asyncio.run(_run(domains, args.min_score))


if __name__ == "__main__":
    main()
