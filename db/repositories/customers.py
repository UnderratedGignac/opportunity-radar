"""Customer repository."""

from __future__ import annotations

from db.supabase_client import get_client


async def get_customer_by_email(email: str) -> dict | None:
    client = await get_client()
    res = (
        await client.table("customers")
        .select("*")
        .eq("email", email)
        .eq("status", "active")
        .single()
        .execute()
    )
    return res.data


async def get_customer(customer_id: str) -> dict | None:
    client = await get_client()
    res = (
        await client.table("customers")
        .select("*")
        .eq("id", customer_id)
        .single()
        .execute()
    )
    return res.data


async def create_customer(data: dict) -> dict:
    client = await get_client()
    res = await client.table("customers").insert(data).execute()
    return res.data[0] if res.data else {}


async def update_customer(customer_id: str, data: dict) -> dict:
    client = await get_client()
    res = (
        await client.table("customers")
        .update(data)
        .eq("id", customer_id)
        .execute()
    )
    return res.data[0] if res.data else {}


async def list_active_customers() -> list[dict]:
    client = await get_client()
    res = (
        await client.table("customers")
        .select("*")
        .eq("status", "active")
        .execute()
    )
    return res.data or []


async def get_customer_by_stripe_id(stripe_id: str) -> dict | None:
    client = await get_client()
    res = (
        await client.table("customers")
        .select("*")
        .eq("stripe_customer_id", stripe_id)
        .single()
        .execute()
    )
    return res.data
