"""Background job processor — scheduled signal scans and weekly digest.

For MVP: runs as a simple async scheduler (no Redis needed).
Month 2+: replace with BullMQ (Node.js) or Celery (Python) with Upstash Redis.

Jobs:
  - Daily at 6 AM UTC: scan all watched companies for new signals
  - Monday 8 AM UTC: send weekly digest to all active customers
  - Sunday 3 AM UTC: run learning agent
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("radar.scheduler.processor")


async def run_daily_scan() -> None:
    """Scan all companies watched by active customers."""
    logger.info("Daily scan started at %s", datetime.now(timezone.utc).isoformat())
    from db.repositories.customers import list_active_customers
    from db.repositories.opportunities import list_opportunities
    from agents.signal_collection_agent import SignalCollectionAgent
    from agents.scoring_agent import ScoringAgent
    from agents.intelligence_agent import IntelligenceAgent
    from agents.outreach_agent import OutreachAgent
    from core.pipeline import CompanyPipeline, RadarOrchestrator
    from config import settings
    from llm.claude_router import ClaudeRouter
    from models.company import CompanyProfile

    customers = await list_active_customers()
    if not customers:
        logger.info("No active customers — skipping scan")
        return

    # Collect all unique domains across customers (deduplicated)
    all_domains: set[str] = set()
    for c in customers:
        for v in (c.get("target_verticals") or []):
            pass  # future: expand verticals to domains
    # For now use a fixed watchlist from env
    import os
    watchlist_raw = os.getenv("WATCHLIST_DOMAINS", "")
    if watchlist_raw:
        all_domains.update(d.strip() for d in watchlist_raw.split(",") if d.strip())

    if not all_domains:
        logger.warning("No domains in WATCHLIST_DOMAINS — scan skipped")
        return

    llm = ClaudeRouter()
    pipeline = CompanyPipeline(
        collector=SignalCollectionAgent(llm=llm, ),
        intelligence=IntelligenceAgent(llm=llm),
        scorer=ScoringAgent(llm=llm),
        outreach=OutreachAgent(llm=llm),
    )
    orchestrator = RadarOrchestrator(pipeline, concurrency=settings.PIPELINE_CONCURRENCY)
    companies = [CompanyProfile(name=d.split(".")[0].title(), domain=d) for d in all_domains]
    packages = await orchestrator.run_batch(companies)

    # Persist high-score opportunities and send Slack alerts
    from db.repositories.opportunities import insert_opportunity, insert_outreach, upsert_company
    from notifications.slack_alerts import broadcast_to_customers

    for pkg in packages:
        opp = pkg.opportunity
        if opp.opportunity_score < settings.MIN_SCORE_THRESHOLD:
            continue
        company_row = await upsert_company(opp.company_domain, opp.company_name)
        company_id = company_row.get("id")
        opp_dict = {
            "company_id": company_id,
            "opportunity_score": opp.opportunity_score,
            "confidence_score": opp.confidence_score,
            "likely_needs": opp.likely_needs,
            "decision_maker_titles": opp.decision_maker_titles,
            "timing_rationale": opp.timing_rationale,
            "score_breakdown": opp.score_breakdown,
        }
        opp_row = await insert_opportunity(opp_dict)
        if opp_row.get("id"):
            await insert_outreach({
                "opportunity_id": opp_row["id"],
                "email_subject": pkg.email_subject,
                "email_body": pkg.email_body,
                "linkedin_message": pkg.linkedin_message,
                "call_opener": pkg.call_opener,
            })
        if opp.opportunity_score >= 80:
            opp_dict["company_name"] = opp.company_name
            opp_dict["signals_summary"] = [s.signal.detail for s in opp.signals[:4]]
            await broadcast_to_customers(opp_dict, customers)

    logger.info("Daily scan complete: %d opportunities persisted", len(packages))


async def run_weekly_digest() -> None:
    """Send weekly email digest to all active customers."""
    logger.info("Weekly digest started")
    from db.repositories.customers import list_active_customers
    from db.repositories.opportunities import list_opportunities
    from notifications.email_digest import send_digest
    customers = await list_active_customers()
    opps = await list_opportunities(min_score=60, limit=20)
    for customer in customers:
        await send_digest(
            to_email=customer["email"],
            customer_name=customer.get("owner_name") or customer["agency_name"],
            opportunities=opps,
        )
    logger.info("Weekly digest sent to %d customers", len(customers))


async def run_learning_cycle() -> None:
    """Run the learning agent — analyze outcomes and log weight recommendations."""
    logger.info("Learning cycle started")
    from agents.learning_agent import LearningAgent
    agent = LearningAgent(auto_apply=False)
    result = await agent.run(days_lookback=30)
    logger.info("Learning cycle result: %s", result.get("status"))


async def _scheduler() -> None:
    """Primitive scheduler — runs jobs at fixed UTC hours. Replace with Celery/cron for prod."""
    import os
    last_daily = -1
    last_weekly = -1
    last_learning = -1

    while True:
        now = datetime.now(timezone.utc)
        hour = now.hour
        weekday = now.weekday()  # 0=Monday, 6=Sunday

        if hour == 6 and last_daily != now.day:
            last_daily = now.day
            asyncio.create_task(run_daily_scan())

        if weekday == 0 and hour == 8 and last_weekly != now.isocalendar()[1]:
            last_weekly = now.isocalendar()[1]
            asyncio.create_task(run_weekly_digest())

        if weekday == 6 and hour == 3 and last_learning != now.isocalendar()[1]:
            last_learning = now.isocalendar()[1]
            asyncio.create_task(run_learning_cycle())

        await asyncio.sleep(60)  # Check every minute


def start_scheduler() -> asyncio.Task:
    return asyncio.create_task(_scheduler())
