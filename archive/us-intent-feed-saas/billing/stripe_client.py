"""Stripe billing integration.

Plans:
  pilot  — $497/month — price_pilot
  growth — $997/month — price_growth
  scale  — $1997/month — price_scale

Stripe webhook verifies payment and activates customer account.
"""

from __future__ import annotations

import logging
import os

import stripe

logger = logging.getLogger("radar.billing.stripe")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

PLAN_PRICE_IDS = {
    "pilot": os.getenv("STRIPE_PRICE_PILOT", "price_pilot"),
    "growth": os.getenv("STRIPE_PRICE_GROWTH", "price_growth"),
    "scale": os.getenv("STRIPE_PRICE_SCALE", "price_scale"),
}


async def create_checkout_session(
    customer_email: str,
    plan: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session and return its URL."""
    price_id = PLAN_PRICE_IDS.get(plan)
    if not price_id:
        raise ValueError(f"Unknown plan: {plan}")
    try:
        session = stripe.checkout.Session.create(
            customer_email=customer_email,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"plan": plan},
        )
        return session.url
    except stripe.error.StripeError as e:
        logger.error("Stripe checkout error: %s", e)
        raise


def verify_webhook(payload: bytes, sig_header: str) -> dict:
    """Verify Stripe webhook signature and return the event."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
        return event
    except (stripe.error.SignatureVerificationError, ValueError) as e:
        raise ValueError(f"Invalid webhook: {e}") from e


async def cancel_subscription(stripe_customer_id: str) -> bool:
    """Cancel all active subscriptions for a customer."""
    try:
        subs = stripe.Subscription.list(customer=stripe_customer_id, status="active")
        for sub in subs.auto_paging_iter():
            stripe.Subscription.cancel(sub.id)
        return True
    except stripe.error.StripeError as e:
        logger.error("Cancel subscription error: %s", e)
        return False
