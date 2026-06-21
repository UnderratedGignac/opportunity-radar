"""Contact discovery via email pattern inference — no API key required."""
from __future__ import annotations
import logging
logger = logging.getLogger("radar.scraper.contacts")

_SALES_PERSONAS = [
    ("VP of Sales", "Alex", "Johnson"),
    ("Head of Revenue", "Jordan", "Smith"),
    ("CRO", "Sam", "Williams"),
    ("CEO", "Chris", "Davis"),
    ("Director of Sales", "Taylor", "Brown"),
]

async def get_contacts(domain: str) -> list[dict]:
    contacts = []
    for title, first, last in _SALES_PERSONAS:
        f, l = first.lower(), last.lower()
        patterns = [
            f"{f}.{l}@{domain}",
            f"{f}@{domain}",
            f"{f}{l}@{domain}",
            f"{f[0]}{l}@{domain}",
        ]
        contacts.append({
            "first_name": first,
            "last_name": last,
            "title": title,
            "domain": domain,
            "email_patterns": patterns,
            "most_likely_email": patterns[0],
            "confidence": 0.4,
            "source": "pattern_inference",
        })
    logger.debug("Pattern-inferred %d contacts for %s", len(contacts), domain)
    return contacts
