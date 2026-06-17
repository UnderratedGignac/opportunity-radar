"""Slack webhook alerts — real-time pings for high-score opportunities."""

from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger("radar.notifications.slack")


def _score_emoji(score: int) -> str:
    if score >= 85:
        return "🔥"
    if score >= 70:
        return "⚡"
    return "📊"


def _build_blocks(opportunity: dict) -> list[dict]:
    opp = opportunity
    score = opp.get("opportunity_score", 0)
    company = opp.get("company_name", "Unknown")
    signals = opp.get("signals_summary") or []
    needs = (opp.get("likely_needs") or [])[:2]
    rationale = opp.get("timing_rationale", "")

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{_score_emoji(score)} New Opportunity: {company} ({score}/100)",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Score:* {score}/100"},
                {"type": "mrkdwn", "text": f"*Confidence:* {opp.get('confidence_score', 0)}%"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Signals detected:*\n" + "\n".join(f"• {s}" for s in signals[:4]),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Likely needs:* {' · '.join(needs)}\n*Why now:* _{rationale}_",
            },
        },
        {"type": "divider"},
    ]


async def send_slack_alert(webhook_url: str, opportunity: dict) -> bool:
    if not webhook_url:
        return False
    payload = {"blocks": _build_blocks(opportunity)}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    logger.info(
                        "Slack alert sent for %s (score=%d)",
                        opportunity.get("company_name"),
                        opportunity.get("opportunity_score", 0),
                    )
                    return True
                body = await resp.text()
                logger.warning("Slack webhook error %d: %s", resp.status, body)
                return False
    except Exception as e:
        logger.error("Slack alert failed: %s", e)
        return False


async def broadcast_to_customers(opportunity: dict, customers: list[dict]) -> None:
    """Send Slack alert to all customers who have a webhook configured."""
    import asyncio
    tasks = [
        send_slack_alert(c["slack_webhook"], opportunity)
        for c in customers
        if c.get("slack_webhook")
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
