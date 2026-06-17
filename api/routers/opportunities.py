"""Opportunities router."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.auth import require_customer

router = APIRouter(prefix="/opportunities", tags=["opportunities"])

# ── Dev mode: return sample data when Supabase isn't configured ───────────────

def _supabase_ready() -> bool:
    url = os.getenv("SUPABASE_URL", "")
    return bool(url) and "xxx" not in url and url != "https://your-project.supabase.co"

_MOCK_OPPORTUNITIES = [
    {
        "id": "demo-001",
        "company_name": "Acme Corp",
        "company_domain": "acme.com",
        "opportunity_score": 87,
        "confidence_score": 82,
        "status": "new",
        "likely_needs": ["Sales automation", "Lead qualification", "CRM integration"],
        "decision_maker_titles": ["VP Sales", "Head of Revenue"],
        "timing_rationale": "Recent Series B funding + 3 open SDR roles signals active sales scale-up.",
        "score_breakdown": [
            {"signal": "Series B funding ($12M)", "weight": 35, "recency": 1.0},
            {"signal": "Hiring: 3x SDR roles", "weight": 28, "recency": 0.85},
            {"signal": "New VP Sales posted", "weight": 24, "recency": 0.9},
        ],
        "outreach": {
            "email_subject": "Congrats on the Series B — quick question about your SDR ramp",
            "email_body": "Hi [Name],\n\nSaw Acme just closed a Series B and is scaling the sales team. Companies at this stage typically need 3–4 months to ramp new SDRs fully.\n\nWe help AI-forward teams cut that ramp to 6 weeks using AI qualification workflows.\n\nWorth a 15-min call this week?",
            "linkedin_message": "Congrats on the raise! Noticed you're scaling the SDR team — curious how you're thinking about ramp time. We've helped similar companies cut it by 60% with AI workflows. Happy to share what's working.",
            "call_opener": "I noticed Acme just raised a Series B and is hiring SDRs — are you finding it hard to get them productive quickly?"
        },
        "signals": [
            {"type": "funding", "detail": "Series B $12M led by Sequoia", "confidence": 0.95},
            {"type": "hiring", "detail": "3 SDR roles posted this week", "confidence": 0.9},
            {"type": "exec_change", "detail": "New VP Sales joined from Salesforce", "confidence": 0.88},
        ],
        "created_at": "2026-06-17T10:00:00Z",
    },
    {
        "id": "demo-002",
        "company_name": "TechFlow",
        "company_domain": "techflow.io",
        "opportunity_score": 74,
        "confidence_score": 70,
        "status": "new",
        "likely_needs": ["Customer onboarding automation", "Support ticket deflection"],
        "decision_maker_titles": ["COO", "Head of Customer Success"],
        "timing_rationale": "Hiring for CS roles while launching new product suggests scaling pain.",
        "score_breakdown": [
            {"signal": "New product launch announced", "weight": 22, "recency": 0.9},
            {"signal": "Hiring: 2 CS Managers", "weight": 20, "recency": 0.85},
        ],
        "outreach": {
            "email_subject": "TechFlow's new product launch — onboarding bottleneck incoming?",
            "email_body": "Hi [Name],\n\nSaw TechFlow launched the new platform last week — congrats. New product launches usually mean a wave of new customers, and onboarding becomes the bottleneck fast.\n\nWe automate onboarding workflows so your CS team can handle 3x the volume without adding headcount.\n\nOpen to a quick call?",
            "linkedin_message": "Congrats on the launch! New products always bring a wave of onboarding work. We help CS teams automate the repetitive parts — happy to show you what that looks like for a similar company.",
            "call_opener": "I saw TechFlow just launched a new product — how are you thinking about scaling onboarding without burning out the CS team?"
        },
        "signals": [
            {"type": "website_change", "detail": "New product page live", "confidence": 0.85},
            {"type": "hiring", "detail": "2 Customer Success Manager roles", "confidence": 0.8},
        ],
        "created_at": "2026-06-17T09:00:00Z",
    },
]

Customer = Annotated[dict, Depends(require_customer)]


class FeedbackPayload(BaseModel):
    action: str  # pursued | not_relevant | demo_booked | converted
    deal_size_usd: int | None = None
    days_to_close: int | None = None
    notes: str | None = None


@router.get("")
async def list_opps(
    customer: Customer,
    min_score: int = Query(60, ge=0, le=100),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    if not _supabase_ready():
        filtered = [o for o in _MOCK_OPPORTUNITIES if o["opportunity_score"] >= min_score]
        return {"data": filtered, "count": len(filtered), "offset": 0, "dev_mode": True}

    from db.repositories.opportunities import list_opportunities
    opps = await list_opportunities(min_score=min_score, status=status_filter, limit=limit, offset=offset)
    return {"data": opps, "count": len(opps), "offset": offset}


@router.get("/{opp_id}")
async def get_opp(opp_id: str, customer: Customer):
    if not _supabase_ready():
        opp = next((o for o in _MOCK_OPPORTUNITIES if o["id"] == opp_id), None)
        if not opp:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        return opp

    from db.repositories.opportunities import get_opportunity
    opp = await get_opportunity(opp_id)
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    return opp


@router.patch("/{opp_id}/status")
async def set_status(opp_id: str, new_status: str, customer: Customer):
    allowed = {"new", "viewed", "pursued", "converted", "not_relevant"}
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {allowed}")
    if not _supabase_ready():
        return {"id": opp_id, "status": new_status, "dev_mode": True}

    from db.repositories.opportunities import update_opportunity_status
    return await update_opportunity_status(opp_id, new_status)


@router.post("/{opp_id}/feedback")
async def submit_feedback(opp_id: str, payload: FeedbackPayload, customer: Customer):
    allowed_actions = {"pursued", "not_relevant", "demo_booked", "converted"}
    if payload.action not in allowed_actions:
        raise HTTPException(status_code=400, detail=f"action must be one of {allowed_actions}")
    if not _supabase_ready():
        return {"ok": True, "feedback_id": "dev-feedback", "dev_mode": True}

    from db.repositories.opportunities import record_feedback, update_opportunity_status
    result = await record_feedback(
        customer_id=customer["id"],
        opportunity_id=opp_id,
        action=payload.action,
        deal_size_usd=payload.deal_size_usd,
        days_to_close=payload.days_to_close,
        notes=payload.notes,
    )
    status_map = {"pursued": "pursued", "not_relevant": "not_relevant", "demo_booked": "pursued", "converted": "converted"}
    await update_opportunity_status(opp_id, status_map[payload.action])
    return {"ok": True, "feedback_id": result.get("id")}
