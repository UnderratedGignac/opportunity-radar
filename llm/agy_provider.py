"""AGY (Antigravity / Gemini CLI) LLM provider.

Drives the locally installed ``agy.exe`` as an inference worker: each call
runs ``agy --print <prompt>`` and captures the response from stdout.

Used by the router as the zero-API-key provider: no Anthropic key is needed —
inference runs through the local Gemini CLI session instead.

Notes:
- agy.exe reliably prints the response to stdout but then hangs on shutdown
  ("waiting for migrations"), so we watch the stdout file and kill the process
  once the output has stabilized instead of waiting for a clean exit.
- Calls are serialized with a module lock (one CLI agent turn at a time).
- Latency is ~10-40s per call, so this provider is for demos and low-volume
  scans, not high-throughput pipelines.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from shutil import which

logger = logging.getLogger(__name__)

_AGY_EXE = os.getenv("AGY_EXE", "agy.exe")
_LOCK = threading.Lock()

# Output is considered complete when the stdout file is non-empty and its
# size has not changed for this many seconds.
_STABLE_SECONDS = 3.0


def available() -> bool:
    """True if agy.exe is on PATH."""
    return which(_AGY_EXE) is not None


def generate(prompt: str, system: str, timeout: int = 180) -> str:
    """Run one inference turn through AGY. Blocking; call via asyncio.to_thread."""
    full_prompt = (
        f"{system}\n\n{prompt}\n\n"
        "Answer directly with text only. Do not read or edit any files, "
        "do not run commands."
    )
    with _LOCK:
        out_path = None
        proc = None
        try:
            fd, out_path = tempfile.mkstemp(prefix="agy_out_", suffix=".txt")
            os.close(fd)
            with open(out_path, "w", encoding="utf-8") as out_file:
                try:
                    proc = subprocess.Popen(
                        [_AGY_EXE, "--print", full_prompt, "--dangerously-skip-permissions"],
                        stdin=subprocess.DEVNULL,  # piped stdin makes AGY block reading it
                        stdout=out_file,
                        stderr=subprocess.DEVNULL,
                        cwd=str(Path(__file__).resolve().parent.parent),
                    )
                except FileNotFoundError:
                    logger.error("agy.exe not found — AGY provider unavailable")
                    return ""

                deadline = time.time() + timeout
                last_size = 0
                stable_since = None
                while time.time() < deadline:
                    time.sleep(0.5)
                    try:
                        size = os.path.getsize(out_path)
                    except OSError:
                        size = 0
                    if size > 0:
                        if size != last_size:
                            last_size = size
                            stable_since = time.time()
                        elif stable_since and time.time() - stable_since >= _STABLE_SECONDS:
                            break  # output landed and stopped growing
                    if proc.poll() is not None:
                        break  # clean exit (rare, but take it)
            # Kill the hung shutdown phase; the answer is already on disk.
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass

            text = Path(out_path).read_text(encoding="utf-8", errors="replace").strip()
            if not text:
                logger.warning("AGY produced no output within %ds", timeout)
            return text
        finally:
            if out_path:
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
