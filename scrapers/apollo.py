"""Contact enrichment — no external API needed.

Returns empty list. Contact finding is done manually or via free LinkedIn search.
Kept as a module so the pipeline import doesn't break.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("radar.scrapers.apollo")


async def get_contacts(domain: str, max_results: int = 5) -> list[dict]:
    """No-op — contact enrichment removed (was Apollo.io, paid service).

    To find contacts manually: search LinkedIn for '<company> VP Sales' or similar.
    """
    return []
