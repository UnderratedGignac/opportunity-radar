"""LLM router — Anthropic Claude API, with a local AGY (Gemini CLI) fallback.

Provider selection (env `LLM_PROVIDER` overrides; default is automatic):
  anthropic — when ANTHROPIC_API_KEY is set (Claude Haiku/Sonnet tiers)
  agy       — otherwise: inference through the locally installed agy.exe
              (Antigravity / Gemini CLI). No API key required.

Model aliases (callers may import these):
  HAIKU  — fast extraction tier  (claude-haiku-4-5-20251001)
  SONNET — reasoning / copy tier (claude-sonnet-4-6)
  OPUS   — deep analysis tier    (claude-sonnet-4-6, same for now)
On the AGY provider all tiers map to the CLI's Gemini model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import anthropic

from llm import agy_provider

logger = logging.getLogger(__name__)


def active_provider() -> str:
    """Which LLM backend this process will use."""
    forced = os.getenv("LLM_PROVIDER", "").strip().lower()
    if forced in ("anthropic", "agy"):
        return forced
    return "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "agy"

# Model name aliases — used by callers (e.g. learning_agent imports SONNET)
HAIKU  = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"
OPUS   = "claude-sonnet-4-6"

_MAX_TOKENS = 1024


def _client() -> anthropic.AsyncAnthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — add it to .env")
    return anthropic.AsyncAnthropic(api_key=api_key)


# ── JSON helpers ──────────────────────────────────────────────────────────────

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


# ── LLM backend ───────────────────────────────────────────────────────────────

async def _call(prompt: str, system: str, json_mode: bool, model: str = HAIKU) -> str:
    if json_mode:
        # Ask the model to respond with JSON only
        prompt = prompt + "\n\nRespond with valid JSON only. No markdown fences."

    if active_provider() == "agy":
        # Local Gemini CLI worker — blocking subprocess, run off the event loop.
        return await asyncio.to_thread(agy_provider.generate, prompt, system)

    client = _client()
    kwargs: dict[str, Any] = {}
    message = await client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    return message.content[0].text


# ── Router ────────────────────────────────────────────────────────────────────

class ClaudeRouter:
    """Anthropic Claude LLM router with circuit breaker."""

    _BREAK_AFTER = 5
    _BREAK_SECONDS = 60

    def __init__(self) -> None:
        self._failures = 0
        self._broken_until = 0.0

    async def extract(self, prompt: str, system: str) -> dict[str, Any]:
        """Fast structured extraction — HAIKU tier."""
        return await self._query_json(prompt, system, model=HAIKU)

    async def analyze(self, prompt: str, system: str) -> dict[str, Any]:
        """Deep reasoning — SONNET tier."""
        return await self._query_json(prompt, system, model=SONNET)

    async def compose(self, prompt: str, system: str) -> str:
        """Long-form text generation — SONNET tier."""
        self._check_circuit()
        try:
            text = await _call(prompt, system, json_mode=False, model=SONNET)
            self._reset_circuit()
            return text.strip()
        except Exception as e:
            self._record_failure(str(e))
            return ""

    async def _query_json(self, prompt: str, system: str, model: str = HAIKU) -> dict[str, Any]:
        self._check_circuit()
        try:
            raw = await _call(prompt, system, json_mode=True, model=model)
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
            self._failures = 0

    def _reset_circuit(self) -> None:
        self._failures = 0

    def _record_failure(self, reason: str) -> None:
        self._failures += 1
        if self._failures >= self._BREAK_AFTER:
            self._broken_until = time.time() + self._BREAK_SECONDS
            logger.error(
                "LLM circuit tripped after %d failures. Pausing %ds.",
                self._failures, self._BREAK_SECONDS,
            )
        else:
            logger.warning(
                "LLM call failed (%d/%d): %s",
                self._failures, self._BREAK_AFTER, reason,
            )
