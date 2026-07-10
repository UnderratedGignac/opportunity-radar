"""Supabase async client wrapper."""

from __future__ import annotations

import os
from functools import lru_cache

from supabase import AsyncClient, acreate_client


@lru_cache(maxsize=1)
def _get_url_key() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
    return url, key


_client: AsyncClient | None = None


async def get_client() -> AsyncClient:
    global _client
    if _client is None:
        url, key = _get_url_key()
        _client = await acreate_client(url, key)
    return _client
