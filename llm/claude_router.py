"""LLM router — delegates to AGY (Antigravity/Gemini CLI) worker.

AGY is the local agy.exe binary that auto-manages Google OAuth and uses
Gemini models under the hood. No API key required — it uses the user's
existing Google auth from ~/.gemini/oauth_creds.json.

Fallback chain:
  1. AGY (agy.exe) — free, auto-auth, Gemini-powered
  2. Gemini HTTP API — if GEMINI_API_KEY is set in .env
  3. Keyword extraction (callers handle this fallback)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

import aiohttp

from tools.agy_bridge import run_task, AgyResult

logger = logging.getLogger(__name__)

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_MODEL = "gemini-2.0-flash-lite"

# Thread pool for blocking AGY calls (1 worker — avoids concurrent DB conflicts)
_AGY_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agy")


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


def _has_gemini_key() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "") or os.getenv("GEMINI_ACCESS_TOKEN", ""))


async def _call_gemini_http(prompt: str, system: str, json_mode: bool) -> str:
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


async def _call_agy(prompt: str, system: str, json_mode: bool) -> str:
    """Run AGY in a thread pool executor to avoid blocking the event loop."""
    full_prompt = f"{system}\n\n{prompt}"
    if json_mode:
        full_prompt += "\n\nRespond with valid JSON only. No markdown fences."

    loop = asyncio.get_event_loop()
    fn = partial(run_task, full_prompt, timeout=90)
    result: AgyResult = await loop.run_in_executor(_AGY_POOL, fn)

    if not result.ok:
        raise RuntimeError(f"AGY failed: {result.error}")

    return result.text


async def _call(prompt: str, system: str, json_mode: bool) -> str:
    """Try AGY first, then Gemini HTTP API."""
    try:
        return await _call_agy(prompt, system, json_mode)
    except Exception as agy_err:
        logger.warning("AGY failed (%s), trying Gemini HTTP...", agy_err)
        if _has_gemini_key():
            return await _call_gemini_http(prompt, system, json_mode)
        raise RuntimeError(f"Both AGY and Gemini HTTP unavailable: {agy_err}") from agy_err


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        inner = parts[1] if len(parts) > 1 else text
        return inner[4:].strip() if inner.startswith("json") else inner.strip()
    return text


def _extract_json_block(text: str) -> str:
    """Pull first balanced {...} or [...] block from text."""
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        idx = text.find(start_char)
        if idx == -1:
            continue
        depth = 0
        in_str = False
        escape = False
        for i, ch in enumerate(text[idx:], idx):
            if escape:
                escape = False
                continue
            if ch == '\\' and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    candidate = text[idx:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break
    return text


class ClaudeRouter:
    """LLM router: AGY worker → Gemini HTTP fallback. Same interface throughout."""

    _failures = 0
    _broken_until = 0.0
    _BREAK_AFTER = 5
    _BREAK_SECONDS = 60

    async def extract(self, prompt: str, system: str) -> dict[str, Any]:
        return await self._query_json(prompt, system)

    async def analyze(self, prompt: str, system: str) -> dict[str, Any]:
        return await self._query_json(prompt, system)

    async def compose(self, prompt: str, system: str) -> str:
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
            raw = _extract_json_block(raw)
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                self._reset_circuit()
                return parsed
            logger.warning("LLM returned non-dict JSON: %s", type(parsed))
        except json.JSONDecodeError as e:
            logger.warning("LLM JSON parse error: %s", e)
        except Exception as e:
            self._record_failure(str(e))
        return {}

    def _check_circuit(self) -> None:
        now = time.time()
        if self._failures >= self._BREAK_AFTER and now < self._broken_until:
            remaining = int(self._broken_until - now)
            raise RuntimeError(f"LLM circuit open — retry in {remaining}s")
        if now >= self._broken_until:
            ClaudeRouter._failures = 0

    def _reset_circuit(self) -> None:
        ClaudeRouter._failures = 0

    def _record_failure(self, reason: str) -> None:
        ClaudeRouter._failures += 1
        if ClaudeRouter._failures >= self._BREAK_AFTER:
            ClaudeRouter._broken_until = time.time() + self._BREAK_SECONDS
            logger.error("LLM circuit tripped after %d failures. Pausing %ds.", self._failures, self._BREAK_SECONDS)
        else:
            logger.warning("LLM call failed (%d/%d): %s", self._failures, self._BREAK_AFTER, reason)
