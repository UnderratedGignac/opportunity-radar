"""Email digest — sends opportunity summaries via Gmail SMTP (free).

Setup (one-time):
  1. Enable 2-Step Verification on your Gmail account
  2. Go to myaccount.google.com/apppasswords → generate an App Password
  3. Set in .env:
       SMTP_USER=your@gmail.com
       SMTP_PASS=xxxx xxxx xxxx xxxx   (the 16-char app password)

If SMTP_USER / SMTP_PASS are not set, emails are skipped and logged instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("radar.notifications.email")


def _build_html(opportunities: list[dict], customer_name: str) -> str:
    rows = ""
    for opp in opportunities[:10]:
        score = opp.get("opportunity_score", 0)
        color = "#22c55e" if score >= 80 else "#f59e0b" if score >= 65 else "#94a3b8"
        signals_html = "".join(
            f"<li style='margin:2px 0;color:#94a3b8;font-size:13px;'>{s}</li>"
            for s in (opp.get("signals_summary") or [])[:3]
        )
        needs_html = " · ".join((opp.get("likely_needs") or [])[:2])
        rows += f"""
        <div style='border:1px solid #1e2537;border-radius:8px;padding:16px;margin-bottom:12px;background:#161b27;'>
          <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;'>
            <strong style='color:#f0f0f0;font-size:15px;'>{opp.get('company_name','')}</strong>
            <span style='background:{color};color:#000;font-size:12px;font-weight:700;
                         padding:3px 10px;border-radius:20px;'>{score}</span>
          </div>
          <ul style='margin:0;padding-left:16px;'>{signals_html}</ul>
          <p style='color:#60a5fa;font-size:12px;margin:8px 0 0;'>{needs_html}</p>
        </div>"""

    date_str = datetime.utcnow().strftime("%B %d, %Y")
    return f"""
    <html><body style='background:#0f1117;font-family:system-ui,sans-serif;padding:24px;max-width:600px;margin:0 auto;'>
      <h2 style='color:#f0f0f0;border-bottom:1px solid #1e2537;padding-bottom:12px;'>
        AI Opportunity Radar — {date_str}
      </h2>
      <p style='color:#94a3b8;'>Hi {customer_name}, here are your top opportunities this week:</p>
      {rows}
      <p style='color:#475569;font-size:12px;margin-top:24px;'>
        View all opportunities at your dashboard.
      </p>
    </body></html>"""


def _send_smtp_sync(
    to_email: str,
    subject: str,
    html: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    from_email: str,
) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


async def send_digest(
    to_email: str,
    customer_name: str,
    opportunities: list[dict],
    subject: str | None = None,
) -> bool:
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    if not smtp_user or not smtp_pass:
        logger.info("SMTP not configured — skipping email for %s (set SMTP_USER + SMTP_PASS)", to_email)
        return False
    if not opportunities:
        return False

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    from_email = os.getenv("FROM_EMAIL", smtp_user)
    subject = subject or f"Your top {min(len(opportunities), 10)} opportunities this week"
    html = _build_html(opportunities, customer_name)

    try:
        await asyncio.to_thread(
            _send_smtp_sync,
            to_email, subject, html,
            smtp_host, smtp_port, smtp_user, smtp_pass, from_email,
        )
        logger.info("Email sent to %s (%d opps)", to_email, len(opportunities))
        return True
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return False


async def send_high_score_alert(
    to_email: str, customer_name: str, opportunity: dict
) -> bool:
    company = opportunity.get("company_name", "Unknown")
    score = opportunity.get("opportunity_score", 0)
    subject = f"High-score opportunity: {company} ({score}/100)"
    return await send_digest(to_email, customer_name, [opportunity], subject=subject)
