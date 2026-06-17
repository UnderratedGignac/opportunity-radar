"""Scan router — trigger on-demand signal scans."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from api.auth import require_customer
from agents.intelligence_agent import IntelligenceAgent
from agents.outreach_agent import OutreachAgent
from agents.scoring_agent import ScoringAgent
from agents.signal_collection_agent import SignalCollectionAgent
from config import settings
from core.pipeline import CompanyPipeline, RadarOrchestrator
from db.repositories.opportunities import insert_opportunity, insert_outreach, upsert_company
from llm.claude_router import ClaudeRouter
from models.company import CompanyProfile

router = APIRouter(prefix="/scan", tags=["scan"])
Customer = Annotated[dict, Depends(require_customer)]


class ScanRequest(BaseModel):
    domains: list[str]
    min_score: int = 60


def _build_pipeline(customer: dict) -> CompanyPipeline:
    llm = ClaudeRouter()
    return CompanyPipeline(
        collector=SignalCollectionAgent(llm=llm),
        intelligence=IntelligenceAgent(llm=llm),
        scorer=ScoringAgent(llm=llm),
        outreach=OutreachAgent(
            llm=llm,
            agency_name=customer.get("agency_name", settings.AGENCY_NAME),
            agency_specialty=customer.get("agency_specialty", settings.AGENCY_SPECIALTY),
        ),
    )


async def _run_scan_and_persist(domains: list[str], min_score: int, customer: dict) -> None:
    pipeline = _build_pipeline(customer)
    orchestrator = RadarOrchestrator(pipeline, concurrency=3)
    companies = [
        CompanyProfile(name=d.split(".")[0].title(), domain=d) for d in domains
    ]
    packages = await orchestrator.run_batch(companies)
    for pkg in packages:
        opp = pkg.opportunity
        if opp.opportunity_score < min_score:
            continue
        company_row = await upsert_company(opp.company_domain, opp.company_name)
        company_id = company_row.get("id")
        opp_row = await insert_opportunity(
            {
                "company_id": company_id,
                "opportunity_score": opp.opportunity_score,
                "confidence_score": opp.confidence_score,
                "likely_needs": opp.likely_needs,
                "decision_maker_titles": opp.decision_maker_titles,
                "timing_rationale": opp.timing_rationale,
                "score_breakdown": opp.score_breakdown,
            }
        )
        if opp_row.get("id"):
            await insert_outreach(
                {
                    "opportunity_id": opp_row["id"],
                    "email_subject": pkg.email_subject,
                    "email_body": pkg.email_body,
                    "linkedin_message": pkg.linkedin_message,
                    "call_opener": pkg.call_opener,
                }
            )


@router.post("")
async def trigger_scan(payload: ScanRequest, customer: Customer, background: BackgroundTasks):
    """Trigger an async signal scan. Results are saved to DB and appear in /opportunities."""
    if len(payload.domains) > 20:
        return {"error": "Max 20 domains per request"}
    background.add_task(_run_scan_and_persist, payload.domains, payload.min_score, customer)
    return {
        "status": "scanning",
        "domains": payload.domains,
        "message": "Scan started. Check /opportunities in 2-5 minutes.",
    }
