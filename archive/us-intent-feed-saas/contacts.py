"""Honest contact-lead suggestions — replaces the fabricated-persona apollo scraper.

Never invents person names. Returns role suggestions with real LinkedIn
people-search URLs plus a generic inbox, and an email-pattern helper for
when a REAL name is known. Deterministic: no network I/O.
"""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

logger = logging.getLogger("radar.scraper.contacts")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0; eliehaddadh1@gmail.com)"}

_ROLE_TITLES = [
    "Founder / CEO",
    "VP of Sales / CRO",
    "Head of Growth / Marketing",
]

_LINKEDIN_SEARCH = "https://www.linkedin.com/search/results/people/?keywords="


def email_patterns(first_name: str, last_name: str, domain: str) -> list[str]:
    """Common corporate email patterns for a REAL, known person name."""
    try:
        f = "".join((first_name or "").split()).lower()
        l = "".join((last_name or "").split()).lower()
        d = _clean_domain(domain)
        if not f or not l or not d:
            return []
        candidates = [f"{f}.{l}@{d}", f"{f}@{d}", f"{f}{l}@{d}", f"{f[0]}{l}@{d}"]
        # single-letter first names collapse patterns into duplicates
        return list(dict.fromkeys(candidates))
    except Exception as e:
        logger.error("email_patterns failed: %s", e)
        return []


async def get_contacts(domain: str, company_name: str | None = None) -> list[dict]:
    """Role-suggestion contact leads for a company. Never fabricates names."""
    try:
        d = _clean_domain(domain)
        if not d:
            logger.warning("get_contacts: bad domain %r", domain)
            return []
        keywords_base = (company_name or "").strip() or d
        contacts = []
        for i, title in enumerate(_ROLE_TITLES):
            contacts.append({
                "first_name": None,
                "last_name": None,
                "title": title,
                "email": f"hello@{d}" if i == 0 else None,
                "linkedin_url": _LINKEDIN_SEARCH + quote_plus(f"{keywords_base} {title}"),
                "company_domain": d,
                "source": "role_suggestion",
                "confidence": 0.3,
            })
        logger.debug("Suggested %d role leads for %s", len(contacts), d)
        return contacts
    except Exception as e:
        logger.error("get_contacts failed for %r: %s", domain, e)
        return []


def _clean_domain(domain: str | None) -> str:
    if not isinstance(domain, str):
        return ""
    d = domain.strip().lower()
    for prefix in ("https://", "http://", "www."):
        d = d.removeprefix(prefix)
    return d.split("/")[0]
