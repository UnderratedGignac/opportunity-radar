"""Caught-hiring freelance pitch generator.

Turns a lead (company caught hiring an automatable role) into a personalized
cold email using the highest-converting angle for Gulf/Lebanon SMBs: reference
the exact role, anchor against the annual salary, and reframe automation as
"handle the repetitive 70%" — never "replace your hire".
"""

from __future__ import annotations

# rough annual salary anchors (USD) by category + geo tier, for the cost frame
_GULF = {"United Arab Emirates", "Saudi Arabia", "Qatar", "Kuwait", "Bahrain", "Oman"}
_SALARY_ANCHOR = {
    "data_entry": (9000, 14000),
    "admin": (11000, 18000),
    "booking": (10000, 16000),
    "support": (10000, 16000),
    "finance": (14000, 22000),
    "marketing": (12000, 20000),
    "sales_ops": (12000, 20000),
}

# category -> the one-line service promise
_SERVICE_LINE = {
    "data_entry": "I build systems that move that data between your tools automatically and keep your sheets and reports up to date with zero manual keying.",
    "admin": "I build automations that handle the scheduling, follow-ups, data entry and reminders — so the admin work runs itself in the background.",
    "booking": "I build WhatsApp + AI systems that confirm bookings 24/7 in Arabic and English, send reminders to kill no-shows, and log everything to your sheet or CRM.",
    "support": "I build an AI support agent that answers the repetitive customer questions instantly in Arabic and English across WhatsApp and email, and escalates only the tricky ones to a person.",
    "finance": "I build automations that generate the invoices, chase overdue payments on WhatsApp and email, and sync the whole flow to QuickBooks or Google Sheets.",
    "marketing": "I build systems that capture every lead from ads, forms and WhatsApp, reply in under a minute, and push them clean into your CRM.",
    "sales_ops": "I build systems that capture every lead from ads, forms and WhatsApp, reply in under a minute, and push them clean into your CRM.",
}

_SENDER = "Elie Haddad"


def _anchor(category: str) -> str:
    lo, hi = _SALARY_ANCHOR.get(category, (10000, 16000))
    mid = (lo + hi) // 2
    return f"~${mid:,}/year"


def build_pitch(lead: dict) -> tuple[str, str]:
    """Return (subject, body) for a caught-hiring lead."""
    company = lead.get("company", "your team")
    role = lead.get("role_title", "that role")
    category = lead.get("category", "admin")
    pain = lead.get("pain", "repetitive manual work that eats the day")
    service = _SERVICE_LINE.get(category, _SERVICE_LINE["admin"])
    country = lead.get("country", "")
    is_gulf = country in _GULF

    subject = f"the {role} you're hiring for — 70% of it can be automated"

    # Arabic moat line (all geos benefit; explicit for Gulf where AR support matters)
    arabic = (
        " Because I'm from the region, the customer-facing side works natively in "
        "Arabic and English — most automation shops can't ship that."
    )

    intro_geo = "in the Gulf" if is_gulf else "in the region"

    body = f"""Hi there,

I saw {company} is hiring for a {role} — congrats on the growth. Before you commit {_anchor(category)} to that seat, one thought: most of that role is {pain}.

{service}{arabic}

The idea isn't to remove the role — it's to let one person handle the work of two by automating the repetitive 70%, or to hold off on the hire while you grow.

I'm a Lebanon-based automation engineer (n8n / Make / AI agents) and I've built exactly this for service businesses {intro_geo}.

Want a 3-minute Loom showing how I'd automate the core of that {role} work for {company}? No call needed — just reply "send it" and I'll record it.

Best,
{_SENDER}
AI Automation Engineer
"""
    return subject, body
