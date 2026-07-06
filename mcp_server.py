"""MCP server for AI Opportunity Radar.

Exposes the radar's pipeline as Model Context Protocol tools so any MCP client
(Claude Desktop, Claude Code, Gemini CLI, custom agents) can drive it:
scan domains, browse scored opportunities, read the generated outreach copy,
and record outcome feedback that trains the LearningAgent.

The server is a thin authenticated client over the running FastAPI backend —
it deliberately reuses the same HTTP surface (and therefore the same
per-customer isolation) as the dashboard, rather than talking to the
database directly.

Run:
    # 1. Start the backend:      python start.py
    # 2. Set your API key:       RADAR_API_KEY=radar_... (from /customers/signup)
    # 3. Register with a client, e.g. Claude Code:
    #    claude mcp add opportunity-radar -e RADAR_API_KEY=radar_... \
    #        -- python mcp_server.py
"""

from __future__ import annotations

import json
import os

import aiohttp
from mcp.server.fastmcp import FastMCP

API_BASE = os.getenv("RADAR_API_URL", "http://127.0.0.1:8000")

mcp = FastMCP(
    "opportunity-radar",
    instructions=(
        "B2B buying-intent radar. Use scan_domains to analyze companies, "
        "list_opportunities to browse scored results, get_opportunity for the "
        "full report incl. outreach copy, and record_feedback to teach the "
        "scoring model what converted."
    ),
)


def _headers() -> dict:
    key = os.getenv("RADAR_API_KEY", "")
    if not key:
        raise RuntimeError("RADAR_API_KEY env var is not set (get one from POST /customers/signup)")
    return {"X-API-Key": key}


async def _get(path: str, params: dict | None = None) -> dict:
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{API_BASE}{path}", params=params, headers=_headers()) as r:
            r.raise_for_status()
            return await r.json()


async def _post(path: str, body: dict) -> dict:
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API_BASE}{path}", json=body, headers=_headers()) as r:
            r.raise_for_status()
            return await r.json()


@mcp.tool()
async def scan_domains(domains: list[str], min_score: int = 60) -> str:
    """Start an async scan of company domains (max 20). The five-agent pipeline
    (signal collection -> intelligence -> scoring -> outreach) runs in the
    background; results land in the opportunity feed after ~2-5 minutes.
    Returns the scan id to poll with scan_status."""
    res = await _post("/scan", {"domains": domains, "min_score": min_score})
    return json.dumps(res)


@mcp.tool()
async def scan_status(scan_id: str) -> str:
    """Check whether a scan started by scan_domains has finished."""
    res = await _get(f"/scan/status/{scan_id}")
    return json.dumps(res)


@mcp.tool()
async def list_opportunities(min_score: int = 60, status: str = "", limit: int = 20) -> str:
    """List scored buying-intent opportunities for the authenticated customer,
    highest score first. status filters to new/pursued/converted/not_relevant."""
    params: dict = {"min_score": min_score, "limit": limit}
    if status:
        params["status"] = status
    res = await _get("/opportunities", params)
    # Compact summary: the full report is available via get_opportunity
    rows = [
        {
            "id": o.get("id"),
            "company": o.get("company_name"),
            "domain": o.get("company_domain"),
            "score": o.get("opportunity_score"),
            "confidence": o.get("confidence_score"),
            "status": o.get("status"),
            "timing_rationale": o.get("timing_rationale"),
        }
        for o in res.get("data", [])
    ]
    return json.dumps({"count": res.get("count"), "opportunities": rows})


@mcp.tool()
async def get_opportunity(opportunity_id: str) -> str:
    """Full report for one opportunity: signals with weights, score breakdown,
    likely needs, decision-maker titles, and the generated outreach copy
    (cold email, LinkedIn message, call opener)."""
    res = await _get(f"/opportunities/{opportunity_id}")
    return json.dumps(res)


@mcp.tool()
async def record_feedback(opportunity_id: str, action: str, deal_size_usd: int = 0) -> str:
    """Record an outcome: pursued, demo_booked, converted, or not_relevant.
    Feedback feeds the weekly LearningAgent, which re-weights the scoring
    formula from real conversions."""
    body: dict = {"action": action}
    if deal_size_usd:
        body["deal_size_usd"] = deal_size_usd
    res = await _post(f"/opportunities/{opportunity_id}/feedback", body)
    return json.dumps(res)


if __name__ == "__main__":
    mcp.run()  # stdio transport
