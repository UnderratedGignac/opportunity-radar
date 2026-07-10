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

SAMPLES_DIR = Path(__file__).parent / "samples"


def _load_teaser(samples_dir: Path = SAMPLES_DIR, count: int = 3) -> list[str]:
    """Top rows of the newest intent_report_*.csv as one-line teasers."""
    try:
        reports = sorted(samples_dir.glob("intent_report_*.csv"))
    except OSError:
        return []
    if not reports:
        return []
    lines: list[str] = []
    with open(reports[-1], newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            company = row.get("Company", "").strip()
            if not company:
                continue
            detail = row.get("FundingDetail", "").strip() or row.get("Signals", "").strip()
            gtm = row.get("GTMOpenRoles", "").strip()
            if gtm and gtm not in ("0", ""):
                plural = "" if gtm == "1" else "s"
                gtm_bit = f"hiring {gtm} GTM role{plural}"
                detail = f"{detail}, {gtm_bit}" if detail else gtm_bit
            lines.append(f"{company} — {detail}" if detail else company)
            if len(lines) >= count:
                break
    return lines


def _build_email(row: dict, to_email: str, teaser: list[str]) -> tuple[str, str]:
    """Return (subject, body) selling the weekly buying-intent feed."""
    company   = row.get("Company", "your agency")
    niche     = row.get("Niche / Specialty", "").strip()
    founder   = row.get("Founder", "").strip()

    greeting = f"Hi {founder.split()[0]}," if founder else "Hi there,"

    # Frame the leads in the prospect's own service language
    niche_lower = niche.lower()
    if "n8n" in niche_lower:
        angle = "n8n automation projects"
    elif "make" in niche_lower or "zapier" in niche_lower:
        angle = "Make.com / Zapier builds"
    elif "voice" in niche_lower:
        angle = "voice AI deployments"
    elif "lead gen" in niche_lower or "outbound" in niche_lower:
        angle = "outbound campaigns"
    elif "revops" in niche_lower or "crm" in niche_lower:
        angle = "RevOps / CRM projects"
    else:
        angle = "AI automation projects"

    if teaser:
        teaser_block = "\n".join(f"• {line}" for line in teaser)
        proof = f"""From this week's scan:

{teaser_block}

Companies like these just got budget and are hiring the roles that usually mean "we need outside help" — the exact window where agencies win {angle}."""
    else:
        proof = f"""Every week it surfaces companies that just got budget and are hiring the roles that usually mean "we need outside help" — the exact window where agencies win {angle}."""

    subject = f"3 warm leads for {company}"

    body = f"""{greeting}

Quick one. I run a system that scans funding announcements, SEC filings, and hiring boards to catch companies at the moment they have fresh budget and an automation problem.

{proof}

Want the full report? 12 companies, each with the why-now, who to contact, and a suggested opener. Reply "send it" and this week's edition is yours, free.

If it's useful: $149/mo for a fresh list every Monday, tuned to your niche. Cancel anytime.

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

    teaser = _load_teaser()
    if not teaser:
        print("WARNING: no samples/intent_report_*.csv found — emails will go out "
              "without the 3-lead teaser. Run report.py first for a stronger pitch.\n")

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
        subject, body = _build_email(row, to_email, teaser)

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
