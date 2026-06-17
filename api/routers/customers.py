"""Customers router — signup, profile, plan management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from api.auth import generate_api_key, hash_key, require_customer
from billing.stripe_client import create_checkout_session
from db.repositories.customers import create_customer, get_customer, update_customer

router = APIRouter(prefix="/customers", tags=["customers"])

Customer = Annotated[dict, Depends(require_customer)]


class SignupPayload(BaseModel):
    agency_name: str
    owner_name: str
    email: EmailStr
    agency_specialty: str = ""
    target_verticals: list[str] = []


class ProfileUpdatePayload(BaseModel):
    agency_specialty: str | None = None
    target_verticals: list[str] | None = None
    target_signals: list[str] | None = None
    slack_webhook: str | None = None


class CheckoutPayload(BaseModel):
    plan: str  # "pilot" | "growth" | "scale"
    success_url: str
    cancel_url: str


@router.post("/signup", status_code=201)
async def signup(payload: SignupPayload):
    """Create a new customer account and return their API key.

    In production, gate this behind Stripe payment confirmation.
    """
    raw_key = generate_api_key()
    customer = await create_customer(
        {
            "agency_name": payload.agency_name,
            "owner_name": payload.owner_name,
            "email": payload.email,
            "agency_specialty": payload.agency_specialty,
            "target_verticals": payload.target_verticals,
            "api_key_hash": hash_key(raw_key),
            "plan": "pilot",
            "status": "active",
        }
    )
    return {
        "customer_id": customer.get("id"),
        "api_key": raw_key,  # shown ONCE — customer must save this
        "message": "Save your API key — it will not be shown again.",
    }


@router.get("/me")
async def get_me(customer: Customer):
    data = await get_customer(customer["id"])
    if not data:
        raise HTTPException(status_code=404, detail="Customer not found")
    data.pop("api_key_hash", None)
    return data


@router.patch("/me")
async def update_me(payload: ProfileUpdatePayload, customer: Customer):
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await update_customer(customer["id"], updates)
    updated.pop("api_key_hash", None)
    return updated


@router.post("/checkout")
async def create_checkout(payload: CheckoutPayload, customer: Customer):
    """Return a Stripe Checkout URL for the requested plan."""
    if payload.plan not in ("pilot", "growth", "scale"):
        raise HTTPException(status_code=400, detail="Invalid plan. Must be pilot, growth, or scale.")
    url = await create_checkout_session(
        customer_email=customer["email"],
        plan=payload.plan,
        success_url=payload.success_url,
        cancel_url=payload.cancel_url,
    )
    return {"checkout_url": url}
