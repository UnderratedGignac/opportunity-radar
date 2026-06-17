"""LLM router — Google Gemini via Bearer token (OAuth access token).

Set in .env:
  GEMINI_ACCESS_TOKEN=AQ.Ab8RN6KG-...   (your OAuth token)

Models used (smallest/fastest):
  gemini-2.0-flash-lite  — extraction + analysis + composition
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_MODEL = "gemini-2.0-flash-lite"


def _token() -> str:
    t = os.getenv("GEMINI_ACCESS_TOKEN", "")
    if not t:
        raise RuntimeError("GEMINI_ACCESS_TOKEN not set in .env")
    return t


def _auth_params() -> dict:
    """Use API key if set, otherwise fall back to Bearer token."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if api_key:
        return {"key": api_key}
    return {}


def _auth_headers() -> dict:
    headers: dict = {"Content-Type": "application/json"}
    api_key = os.getenv("GEMINI_API_KEY", "")
    if api_key:
        headers["x-goog-api-key"] = api_key
    else:
        token = os.getenv("GEMINI_ACCESS_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


async def _call(prompt: str, system: str, json_mode: bool) -> str:
    url = f"{_BASE}/{_MODEL}:generateContent"
    payload: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if json_mode:
        payload["generationConfig"] = {"responseMimeType": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers=_auth_headers(),
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Gemini HTTP {resp.status}: {body[:300]}")
            data = await resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]


class ClaudeRouter:
    """Gemini Bearer-token router. Same interface used throughout the project."""

    _failures = 0
    _broken_until = 0.0
    _BREAK_AFTER = 5
    _BREAK_SECONDS = 60

    async def extract(self, prompt: str, system: str) -> dict[str, Any]:
        """JSON extraction. Returns {} on failure."""
        return await self._query_json(prompt, system)

    async def analyze(self, prompt: str, system: str) -> dict[str, Any]:
        """Analysis — JSON output. Returns {} on failure."""
        return await self._query_json(prompt, system)

    async def compose(self, prompt: str, system: str) -> str:
        """Free-text generation. Returns '' on failure."""
        self._check_circuit()
        try:
            text = await _call(prompt, system, json_mode=False)
            self._reset_circuit()
            return text.strip()
        except Exception as e:
            self._record_failure(str(e))
            return ""

    async def _query_json(self, prompt: str, system: str) -> dict[str, Any]:
        self._check_circuit()
        try:
            raw = await _call(prompt, system, json_mode=True)
            raw = _strip_fences(raw.strip())
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                self._reset_circuit()
                return parsed
            logger.warning("Gemini returned non-dict JSON: %s", type(parsed))
        except json.JSONDecodeError as e:
            logger.warning("Gemini JSON parse error: %s", e)
        except Exception as e:
            self._record_failure(str(e))
        return {}

    def _check_circuit(self) -> None:
        now = time.time()
        if self._failures >= self._BREAK_AFTER and now < self._broken_until:
            remaining = int(self._broken_until - now)
            raise RuntimeError(f"Gemini circuit open — retry in {remaining}s")
        if now >= self._broken_until:
            ClaudeRouter._failures = 0

    def _reset_circuit(self) -> None:
        ClaudeRouter._failures = 0

    def _record_failure(self, reason: str) -> None:
        ClaudeRouter._failures += 1
        if ClaudeRouter._failures >= self._BREAK_AFTER:
            ClaudeRouter._broken_until = time.time() + self._BREAK_SECONDS
            logger.error(
                "Gemini circuit tripped after %d failures. Pausing %ds.",
                ClaudeRouter._failures, self._BREAK_SECONDS,
            )
        else:
            logger.warning(
                "Gemini call failed (%d/%d): %s",
                self._failures, self._BREAK_AFTER, reason,
            )


def _strip_fences(text: str) -> str:
    if text.startswith("```"):
        parts = text.split("```")
        inner = parts[1] if len(parts) > 1 else text
        return inner[4:].strip() if inner.startswith("json") else inner.strip()
    return text
