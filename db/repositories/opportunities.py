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
    try:
        res = await client.table("opportunities").insert(opp).execute()
    except Exception as e:
        if "customer_id" in str(e) and "customer_id" in opp:
            opp_copy = {k: v for k, v in opp.items() if k != "customer_id"}
            res = await client.table("opportunities").insert(opp_copy).execute()
        else:
            raise
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
    customer_id: str | None = None,
) -> list[dict]:
    client = await get_client()

    def _build_query(with_customer: bool):
        q = (
            client.table("opportunities")
            .select("*, companies(*), outreach_packages(*)")
            .gte("opportunity_score", min_score)
            .order("opportunity_score", desc=True)
            .range(offset, offset + limit - 1)
        )
        if status:
            q = q.eq("status", status)
        if with_customer and customer_id:
            q = q.eq("customer_id", customer_id)
        return q

    try:
        res = await _build_query(with_customer=True).execute()
    except Exception as e:
        if "customer_id" in str(e):
            res = await _build_query(with_customer=False).execute()
        else:
            raise
    return res.data or []


async def get_opportunity(opp_id: str) -> dict | None:
    client = await get_client()
    try:
        res = (
            await client.table("opportunities")
            .select("*, companies(*), outreach_packages(*)")
            .eq("id", opp_id)
            .single()
            .execute()
        )
        return res.data
    except Exception:
        return None


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
