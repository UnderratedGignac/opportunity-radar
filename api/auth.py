"""Simple API key authentication for MVP.

Customers get an API key on signup. Pass it as:
  Authorization: Bearer <api_key>
or
  X-API-Key: <api_key>

Replace with Supabase Auth (JWT) in Month 3+.
"""

from __future__ import annotations

import hashlib
import os
import secrets

from fastapi import HTTPException, Request, status

from db.repositories.customers import get_customer_by_email


def generate_api_key() -> str:
    return f"radar_{secrets.token_urlsafe(32)}"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def require_customer(request: Request) -> dict:
    """FastAPI dependency — extracts and validates the API key."""
    raw_key = (
        request.headers.get("X-API-Key")
        or _bearer(request.headers.get("Authorization", ""))
    )
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required (X-API-Key header or Bearer token)",
        )

    # In production: query customers table by hashed key.
    # For MVP: check against a hardcoded dev key in env (skip DB for speed).
    dev_key = os.getenv("DEV_API_KEY", "")
    if dev_key and raw_key == dev_key:
        return {"id": "dev", "agency_name": "Dev Agency", "plan": "pilot", "email": "dev@dev.com"}

    # Fetch customer by hashed key from Supabase
    from db.supabase_client import get_client
    client = await get_client()
    key_hash = hash_key(raw_key)
    res = (
        await client.table("customers")
        .select("*")
        .eq("api_key_hash", key_hash)
        .eq("status", "active")
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )
    return res.data


def _bearer(header: str) -> str:
    if header.startswith("Bearer "):
        return header[7:].strip()
    return ""
