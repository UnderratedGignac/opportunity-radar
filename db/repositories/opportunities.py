"""Opportunity repository — Supabase CRUD."""

from __future__ import annotations

from uuid import UUID

from db.supabase_client import get_client


async def upsert_company(domain: str, name: str, **kwargs) -> dict:
    client = await get_client()
    data = {"domain": domain, "name": name, **kwargs}
    res = await client.table("companies").upsert(data, on_conflict="domain").execute()
    return res.data[0] if res.data else {}


async def insert_signal(company_id: str, signal_type: str, detail: str, **kwargs) -> dict:
    client = await get_client()
    data = {"company_id": company_id, "signal_type": signal_type, "signal_detail": detail, **kwargs}
    res = await client.table("signals").insert(data).execute()
    return res.data[0] if res.data else {}


async def insert_opportunity(opp: dict) -> dict:
    client = await get_client()
    res = await client.table("opportunities").insert(opp).execute()
    return res.data[0] if res.data else {}


async def insert_outreach(package: dict) -> dict:
    client = await get_client()
    res = await client.table("outreach_packages").insert(package).execute()
    return res.data[0] if res.data else {}


async def list_opportunities(
    min_score: int = 0,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    client = await get_client()
    q = (
        client.table("opportunities")
        .select("*, companies(*), outreach_packages(*)")
        .gte("opportunity_score", min_score)
        .order("opportunity_score", desc=True)
        .range(offset, offset + limit - 1)
    )
    if status:
        q = q.eq("status", status)
    res = await q.execute()
    return res.data or []


async def get_opportunity(opp_id: str) -> dict | None:
    client = await get_client()
    res = (
        await client.table("opportunities")
        .select("*, companies(*), outreach_packages(*)")
        .eq("id", opp_id)
        .single()
        .execute()
    )
    return res.data


async def update_opportunity_status(opp_id: str, status: str) -> dict:
    client = await get_client()
    res = (
        await client.table("opportunities")
        .update({"status": status})
        .eq("id", opp_id)
        .execute()
    )
    return res.data[0] if res.data else {}


async def get_signal_weights() -> dict[str, float]:
    client = await get_client()
    res = await client.table("signal_weights").select("signal_key,base_weight").execute()
    return {row["signal_key"]: row["base_weight"] for row in (res.data or [])}


async def update_signal_weight(signal_key: str, weight: float, rationale: str, sample_size: int) -> None:
    client = await get_client()
    await (
        client.table("signal_weights")
        .upsert(
            {
                "signal_key": signal_key,
                "base_weight": weight,
                "update_rationale": rationale,
                "sample_size": sample_size,
            },
            on_conflict="signal_key",
        )
        .execute()
    )


async def get_feedback_for_learning(days: int = 30) -> list[dict]:
    client = await get_client()
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = (
        await client.table("opportunity_feedback")
        .select("*, opportunities(opportunity_score, score_breakdown)")
        .gte("created_at", cutoff)
        .execute()
    )
    return res.data or []


async def record_feedback(
    customer_id: str, opportunity_id: str, action: str, **kwargs
) -> dict:
    client = await get_client()
    data = {
        "customer_id": customer_id,
        "opportunity_id": opportunity_id,
        "action": action,
        **kwargs,
    }
    res = await client.table("opportunity_feedback").insert(data).execute()
    return res.data[0] if res.data else {}
