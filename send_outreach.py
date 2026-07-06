"""Outreach email sender — reads prospect_list.csv, sends personalized cold
emails via Gmail SMTP, updates the CSV with sent status.

Usage:
    python send_outreach.py              # live send (asks for confirmation)
    python send_outreach.py --dry-run    # preview emails, send nothing
    python send_outreach.py --limit 5    # send to first 5 unsent contacts

Required env vars (set in .env):
    SMTP_USER   your Gmail address (e.g. eliehaddadh1@gmail.com)
    SMTP_PASS   Gmail App Password (myaccount.google.com/apppasswords)
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

SENDER_NAME    = "Elie Haddad"
SENDER_EMAIL   = os.getenv("SMTP_USER", "eliehaddadh1@gmail.com")
SMTP_PASS      = os.getenv("SMTP_PASS", "")
SMTP_HOST      = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT", "587"))

CSV_PATH = Path(__file__).parent / "prospect_list.csv"

# Delay between sends to avoid spam triggers (seconds)
SEND_DELAY = 30


# ── Email address helpers ─────────────────────────────────────────────────────

def _domain_from_website(url: str) -> str:
    """Extract bare domain from URL or empty string."""
    url = url.strip().lower()
    if not url:
        return ""
    url = re.sub(r"^https?://", "", url)
    url = url.split("/")[0]
    return url


def _guess_emails(row: dict) -> list[str]:
    """Return ordered list of email addresses to try for a prospect."""
    emails: list[str] = []

    # Use explicit email if provided
    explicit = row.get("Email", "").strip()
    if explicit:
        emails.append(explicit)
        return emails

    domain = _domain_from_website(row.get("Website", ""))
    if not domain:
        return []

    # Try founder name-based email first if we have a name
    founder = row.get("Founder", "").strip()
    if founder:
        parts = founder.lower().split()
        if len(parts) >= 2:
            emails.append(f"{parts[0]}.{parts[-1]}@{domain}")
            emails.append(f"{parts[0][0]}{parts[-1]}@{domain}")
        if parts:
            emails.append(f"{parts[0]}@{domain}")

    # Generic fallbacks
    emails += [f"hello@{domain}", f"info@{domain}", f"contact@{domain}"]
    return emails


# ── Email template ────────────────────────────────────────────────────────────

def _build_email(row: dict, to_email: str) -> tuple[str, str]:
    """Return (subject, body) for a prospect row."""
    company   = row.get("Company", "your company")
    niche     = row.get("Niche / Specialty", "AI automation").strip() or "AI automation"
    founder   = row.get("Founder", "").strip()

    greeting = f"Hi {founder.split()[0]}," if founder else "Hi there,"

    # Pick a hook based on niche keywords
    niche_lower = niche.lower()
    if "n8n" in niche_lower:
        angle = "n8n workflow systems"
    elif "make" in niche_lower or "zapier" in niche_lower:
        angle = "Make.com / Zapier automations"
    elif "voice" in niche_lower:
        angle = "voice AI agent pipelines"
    elif "lead gen" in niche_lower or "outbound" in niche_lower:
        angle = "outbound lead-gen automation"
    elif "revops" in niche_lower or "crm" in niche_lower:
        angle = "RevOps and CRM automation"
    elif "healthcare" in niche_lower or "hipaa" in niche_lower:
        angle = "HIPAA-compliant automation pipelines"
    else:
        angle = "AI agent and automation builds"

    subject = f"Freelance AI/Automation Engineer - {company}"

    body = f"""{greeting}

I came across {company} and was impressed by your work in {niche}.

I'm Elie Haddad, a freelance AI automation engineer with hands-on experience building {angle} — end-to-end, from scraping and data pipelines through to LLM integration and deployment.

I'm looking to take on contract work with agencies like yours and would love to contribute to client projects or internal tooling.

A few things I've shipped recently:
• AI-powered outreach pipeline (signal detection → scoring → personalized copy)
• Multi-agent job application system with Gmail, calendar, and portal automation
• B2B lead discovery scrapers with Bing News, Crunchbase RSS, and Apify integrations

Would you be open to a quick call this week to explore fit?

Best,
Elie Haddad
eliehaddadh1@gmail.com
"""
    return subject, body


# ── SMTP sender ───────────────────────────────────────────────────────────────

def _send(to_email: str, subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SENDER_EMAIL, SMTP_PASS)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())


# ── CSV helpers ───────────────────────────────────────────────────────────────

def _load_csv() -> tuple[list[dict], list[str]]:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    return rows, list(fieldnames)


def _save_csv(rows: list[dict], fieldnames: list[str]) -> None:
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Send outreach emails from prospect_list.csv")
    parser.add_argument("--dry-run", action="store_true", help="Preview emails without sending")
    parser.add_argument("--limit", type=int, default=0, help="Max emails to send (0 = all)")
    args = parser.parse_args()

    if not args.dry_run and not SMTP_PASS:
        print("ERROR: SMTP_PASS not set. Add it to .env (Gmail App Password).")
        print("  Guide: myaccount.google.com/apppasswords")
        sys.exit(1)

    rows, fieldnames = _load_csv()

    pending = [r for r in rows if r.get("Contacted?", "No").strip().lower() != "yes"]
    if args.limit:
        pending = pending[: args.limit]

    if not pending:
        print("No pending contacts found. All rows already marked as contacted.")
        return

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Found {len(pending)} contacts to email.\n")

    if not args.dry_run:
        confirm = input(f"Send {len(pending)} emails? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    sent = 0
    skipped = 0

    for row in pending:
        company = row.get("Company", "Unknown")
        candidates = _guess_emails(row)

        if not candidates:
            print(f"  [SKIP]  {company} — no email or website found")
            skipped += 1
            continue

        to_email = candidates[0]
        subject, body = _build_email(row, to_email)

        if args.dry_run:
            print(f"  [DRY]   {company}")
            print(f"          To:      {to_email}")
            print(f"          Subject: {subject}")
            print(f"          Body preview: {body[:120].strip()}...")
            print()
            continue

        try:
            _send(to_email, subject, body)
            row["Contacted?"] = "Yes"
            _save_csv(rows, fieldnames)
            print(f"  [SENT]  {company} → {to_email}")
            sent += 1
            if sent < len(pending):
                time.sleep(SEND_DELAY)
        except Exception as e:
            print(f"  [FAIL]  {company} → {to_email}: {e}")
            skipped += 1

    if not args.dry_run:
        print(f"\nDone. Sent: {sent}  Skipped/failed: {skipped}")
        print("prospect_list.csv updated.")


if __name__ == "__main__":
    main()
