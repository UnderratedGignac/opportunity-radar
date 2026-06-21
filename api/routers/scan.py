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

import csv as _csv
import io as _io
import re as _re
import time
import uuid as _uuid
from collections import defaultdict
from datetime import datetime as _dt

from fastapi import HTTPException, UploadFile, File

_scan_counts: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 600
_RATE_MAX = 5
_scans: dict[str, dict] = {}


def _rate_check(customer_id: str) -> bool:
    now = time.time()
    _scan_counts[customer_id] = [t for t in _scan_counts[customer_id] if t > now - _RATE_WINDOW]
    if len(_scan_counts[customer_id]) >= _RATE_MAX:
        return False
    _scan_counts[customer_id].append(now)
    return True


def _new_scan(domains: list[str]) -> str:
    sid = _uuid.uuid4().hex[:12]
    _scans[sid] = {
        "id": sid, "domains": domains, "status": "running",
        "started_at": _dt.utcnow().isoformat(),
        "completed_at": None, "found": 0, "error": None,
    }
    return sid


def _finish_scan(sid: str, found: int = 0, error: str | None = None) -> None:
    if sid in _scans:
        _scans[sid].update({
            "status": "error" if error else "complete",
            "completed_at": _dt.utcnow().isoformat(),
            "found": found, "error": error,
        })


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


async def _run_scan_and_persist(domains: list[str], min_score: int, customer: dict, scan_id: str = "") -> None:
    customer_id = customer.get("id", "")
    count = 0
    error_msg = None
    try:
        pipeline = _build_pipeline(customer)
        orchestrator = RadarOrchestrator(pipeline, concurrency=3)
        companies = [CompanyProfile(name=d.split(".")[0].title(), domain=d) for d in domains]
        packages = await orchestrator.run_batch(companies)
        for pkg in packages:
            opp = pkg.opportunity
            if opp.opportunity_score < min_score:
                continue
            company_row = await upsert_company(opp.company_domain, opp.company_name)
            company_id = company_row.get("id")
            opp_data = {
                "company_id": company_id,
                "opportunity_score": opp.opportunity_score,
                "confidence_score": opp.confidence_score,
                "likely_needs": opp.likely_needs,
                "decision_maker_titles": opp.decision_maker_titles,
                "timing_rationale": opp.timing_rationale,
                "score_breakdown": opp.score_breakdown,
            }
            if customer_id:
                opp_data["customer_id"] = customer_id
            opp_row = await insert_opportunity(opp_data)
            if opp_row.get("id"):
                await insert_outreach({
                    "opportunity_id": opp_row["id"],
                    "email_subject": pkg.email_subject,
                    "email_body": pkg.email_body,
                    "linkedin_message": pkg.linkedin_message,
                    "call_opener": pkg.call_opener,
                })
                count += 1
    except Exception as e:
        error_msg = str(e)
    finally:
        if scan_id:
            _finish_scan(scan_id, found=count, error=error_msg)


@router.post("")
async def trigger_scan(payload: ScanRequest, customer: Customer, background: BackgroundTasks):
    """Trigger an async signal scan. Results are saved to DB and appear in /opportunities."""
    if len(payload.domains) > 20:
        return {"error": "Max 20 domains per request"}
    from fastapi import HTTPException
    if not _rate_check(customer.get("id", "anon")):
        raise HTTPException(status_code=429, detail="Rate limit: max 5 scans per 10 minutes")

    valid = [d.strip().lower() for d in payload.domains
             if _re.match(r'^[a-z0-9][a-z0-9\-\.]+\.[a-z]{2,}$', d.strip().lower())]
    if not valid:
        raise HTTPException(400, "No valid domains. Use format: example.com")
    payload.domains = valid
    scan_id = _new_scan(payload.domains)
    background.add_task(_run_scan_and_persist, payload.domains, payload.min_score, customer, scan_id)
    return {
        "status": "scanning",
        "scan_id": scan_id,
        "domains": payload.domains,
        "message": "Scan started. Check /opportunities in 2-5 minutes.",
    }


@router.get("/status/{scan_id}")
async def get_scan_status(scan_id: str, customer: Customer):
    s = _scans.get(scan_id)
    if not s:
        raise HTTPException(404, "Scan not found")
    return s


@router.post("/bulk")
async def trigger_bulk_scan(
    customer: Customer,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    min_score: int = 20,
):
    """Upload a CSV file (one domain per row, first column) — scans up to 50 domains."""
    if not (file.filename or "").endswith(".csv"):
        raise HTTPException(400, "Must upload a .csv file")
    content = await file.read()
    reader = _csv.reader(_io.StringIO(content.decode("utf-8", errors="replace")))
    domains = []
    for row in reader:
        if not row:
            continue
        domain = row[0].strip().lower().removeprefix("http://").removeprefix("https://").split("/")[0]
        if _re.match(r'^[a-z0-9][a-z0-9\-\.]+\.[a-z]{2,}$', domain):
            domains.append(domain)
        if len(domains) >= 50:
            break
    if not domains:
        raise HTTPException(400, "No valid domains in CSV. Column 1 should contain: stripe.com")
    scan_id = _new_scan(domains)
    background.add_task(_run_scan_and_persist, domains, min_score, customer, scan_id)
    return {
        "status": "scanning", "scan_id": scan_id,
        "domains_queued": len(domains), "preview": domains[:5],
        "message": f"Bulk scan started for {len(domains)} domains.",
    }
