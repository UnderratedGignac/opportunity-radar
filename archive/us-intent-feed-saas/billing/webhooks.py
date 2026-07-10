"""Stripe webhook handler — FastAPI router."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from billing.stripe_client import verify_webhook
from db.repositories.customers import get_customer_by_stripe_id, update_customer

router = APIRouter(prefix="/webhooks/stripe", tags=["billing"])
logger = logging.getLogger("radar.billing.webhooks")


@router.post("")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = verify_webhook(payload, sig)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await _handle_checkout_complete(data)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_cancelled(data)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data)

    return {"received": True}


async def _handle_checkout_complete(session: dict) -> None:
    stripe_customer_id = session.get("customer")
    customer_email = session.get("customer_email")
    plan = (session.get("metadata") or {}).get("plan", "pilot")
    logger.info("Checkout complete: %s plan=%s", customer_email, plan)
    # Activate customer account
    from db.supabase_client import get_client
    client = await get_client()
    await (
        client.table("customers")
        .update({"stripe_customer_id": stripe_customer_id, "plan": plan, "status": "active"})
        .eq("email", customer_email)
        .execute()
    )


async def _handle_subscription_cancelled(subscription: dict) -> None:
    stripe_customer_id = subscription.get("customer")
    customer = await get_customer_by_stripe_id(stripe_customer_id)
    if customer:
        from datetime import datetime, timezone
        await update_customer(
            customer["id"],
            {"status": "churned", "churned_at": datetime.now(timezone.utc).isoformat()},
        )
        logger.info("Customer churned: %s", customer.get("email"))


async def _handle_payment_failed(invoice: dict) -> None:
    stripe_customer_id = invoice.get("customer")
    customer = await get_customer_by_stripe_id(stripe_customer_id)
    if customer:
        logger.warning("Payment failed for customer: %s", customer.get("email"))
