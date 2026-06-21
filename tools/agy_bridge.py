"""AGY (Antigravity/Gemini CLI) bridge — adapted for Opportunity Radar.

Dispatches prompts to the local agy.exe worker and reads responses from
the SQLite conversation DB that AGY writes to.
"""

import glob
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

_CONV_DIR = Path.home() / ".gemini" / "antigravity-cli" / "conversations"
_AGY_EXE = "agy.exe"

_RESP_STEP_TYPE = 15  # model response turn
_STATUS_DONE = 3      # completed


@dataclass
class AgyResult:
    text: str
    ok: bool
    conversation_id: str
    error: str = ""


def _max_step_idx(db_path: str) -> int:
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        idx = conn.execute("SELECT COALESCE(MAX(idx), -1) FROM steps").fetchone()[0]
        conn.close()
        return idx
    except Exception:
        return -1


def _extract_text(db_path: str, min_idx: int = -1) -> str:
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        row = conn.execute(
            "SELECT step_payload FROM steps "
            "WHERE step_type=? AND status=? AND idx>? "
            "ORDER BY idx DESC LIMIT 1",
            (_RESP_STEP_TYPE, _STATUS_DONE, min_idx),
        ).fetchone()
        if not row or not row[0]:
            return ""
        raw = row[0].decode("utf-8", errors="replace")
        candidates = re.findall(r"[ -~\n\t]{15,}", raw)
        seen, parts = set(), []
        for c in candidates:
            c = c.strip()
            if c and c not in seen and not _is_noise(c):
                seen.add(c)
                parts.append(c)
        return "\n".join(parts)
    finally:
        conn.close()


def _is_noise(s: str) -> bool:
    if re.match(r"^[0-9a-f\-]{36}$", s):
        return True
    if s.startswith(("file:///", "C:\\", "C:/", "/c/")):
        return True
    if s.startswith(("command(", "execute_url(", "read_url(")):
        return True
    if re.match(r"^[0-9a-fA-F]{16,}$", s):
        return True
    return False


def _snapshot_all_dbs() -> dict[str, int]:
    return {db: _max_step_idx(db) for db in glob.glob(str(_CONV_DIR / "*.db"))}


def run_task(prompt: str, *, timeout: int = 90, cwd: str | None = None) -> AgyResult:
    """Dispatch a prompt to AGY and return its response."""
    _CONV_DIR.mkdir(parents=True, exist_ok=True)
    before = _snapshot_all_dbs()

    cmd = [_AGY_EXE, "--print", prompt, "--dangerously-skip-permissions"]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=cwd or os.getcwd(),
        )
    except FileNotFoundError:
        return AgyResult(text="", ok=False, conversation_id="", error="agy.exe not found on PATH")

    deadline = time.time() + timeout
    found_db: str | None = None
    found_min_idx: int = -1

    while time.time() < deadline:
        time.sleep(1)
        for db_path in glob.glob(str(_CONV_DIR / "*.db")):
            prior_idx = before.get(db_path, -1)
            if _max_step_idx(db_path) > prior_idx:
                try:
                    conn = sqlite3.connect(db_path, timeout=2)
                    n = conn.execute(
                        "SELECT COUNT(*) FROM steps WHERE step_type=? AND status=? AND idx>?",
                        (_RESP_STEP_TYPE, _STATUS_DONE, prior_idx),
                    ).fetchone()[0]
                    conn.close()
                    if n > 0:
                        found_db, found_min_idx = db_path, prior_idx
                        break
                except Exception:
                    pass
        if found_db:
            break
        if proc.poll() is not None:
            time.sleep(2)
            for db_path in glob.glob(str(_CONV_DIR / "*.db")):
                prior_idx = before.get(db_path, -1)
                if _max_step_idx(db_path) > prior_idx:
                    try:
                        conn = sqlite3.connect(db_path, timeout=2)
                        n = conn.execute(
                            "SELECT COUNT(*) FROM steps WHERE step_type=? AND status=? AND idx>?",
                            (_RESP_STEP_TYPE, _STATUS_DONE, prior_idx),
                        ).fetchone()[0]
                        conn.close()
                        if n > 0:
                            found_db, found_min_idx = db_path, prior_idx
                    except Exception:
                        pass
            break

    if proc.poll() is None:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if not found_db:
        return AgyResult(text="", ok=False, conversation_id="", error=f"No AGY response within {timeout}s")

    text = _extract_text(found_db, min_idx=found_min_idx)
    return AgyResult(
        text=text,
        ok=bool(text),
        conversation_id=Path(found_db).stem,
        error="" if text else "DB found but no text extracted",
    )
