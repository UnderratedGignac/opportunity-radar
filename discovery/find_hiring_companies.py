#!/usr/bin/env python
"""Discovery concierge: find companies hiring AI engineers / software developers.

Fans a single "who is hiring" web-scrape job across the three live CDP workers
(Qwen with web search, MiniMax's autonomous cloud agent, Gemini Pro grounded in
Google Search), merges + dedupes their findings, and writes a prospect CSV.

This is a *concierge tool* for building the weekly high-intent prospect list
(GTM Phase 2), NOT part of the runtime pipeline.

Usage:
    python discovery/find_hiring_companies.py [N]     # N companies per worker (default 15)
"""
from __future__ import annotations

import concurrent.futures
import csv
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\Elie\.claude")
from tools.workers import gemini, minimax, qwen  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).resolve().parent / "hiring_companies.csv"

PROMPT = """You have LIVE web access — USE it (search the web, open job boards and company careers pages).

Find {n} REAL companies that have POSTED job openings for "AI Engineer", "Machine Learning Engineer",
or "Software Developer / Software Engineer" roles within roughly the last 30 days.

Prefer companies actively SCALING their engineering or AI team — several open roles, recent funding,
or a brand-new AI team. Those are the strongest "investing in tech right now" buying signals.

For EACH company return an object with EXACTLY these keys:
  "company"    : official company name (string)
  "website"    : primary website domain like "acme.com" (string or null)
  "roles"      : the specific AI/SWE role title(s) posted (string)
  "location"   : main job or HQ location (string or null)
  "source_url" : a URL where the posting can be verified - job board listing or careers page (string or null)
  "signal"     : one short why-now phrase, e.g. "8 open AI roles", "just raised Series B" (string)

Output ONLY a valid JSON array of these objects. No prose, no explanation, no markdown code fences.
Do NOT invent companies - only include ones you actually find with current postings."""


def extract_json_array(text: str) -> list:
    """Best-effort pull of a JSON array/object out of a worker's text reply."""
    if not text:
        return []
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        v = json.loads(t)
        return v if isinstance(v, list) else [v]
    except Exception:
        pass
    i, j = t.find("["), t.rfind("]")
    if i != -1 and j > i:
        try:
            v = json.loads(t[i : j + 1])
            return v if isinstance(v, list) else [v]
        except Exception:
            pass
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j > i:
        try:
            return [json.loads(t[i : j + 1])]
        except Exception:
            pass
    return []


def norm_key(website, company) -> str:
    """Dedup key: normalized domain if present, else lowercased company name."""
    if website:
        d = str(website).strip().lower()
        d = re.sub(r"^https?://", "", d)
        d = re.sub(r"^www\.", "", d)
        d = d.split("/")[0].strip()
        if d:
            return d
    return (company or "").strip().lower()


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).strip()


def run_worker(name, fn, n):
    try:
        if name == "qwen":
            r = fn(PROMPT.format(n=n), timeout=150, web_search=True)
        else:
            r = fn(PROMPT.format(n=n), timeout=240)
        rows = extract_json_array(r.text) if r.ok else []
        print(f"[{name}] ok={r.ok} time={r.timing_s:.1f}s parsed={len(rows)} err={r.error!r}")
        if r.ok and not rows:
            print(f"[{name}] RAW (first 500): {r.text[:500]!r}")
        return name, rows
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] EXCEPTION {type(e).__name__}: {e}")
        return name, []


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    print(f"[discovery] requesting {n} companies/worker -> {OUT}")
    t0 = time.time()

    workers = [("qwen", qwen), ("minimax", minimax), ("gemini", gemini)]
    results: dict[str, list] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(run_worker, name, fn, n) for name, fn in workers]
        for f in concurrent.futures.as_completed(futs):
            name, rows = f.result()
            results[name] = rows

    merged: dict[str, dict] = {}
    for name, rows in results.items():
        for row in rows:
            if not isinstance(row, dict):
                continue
            company = _s(row.get("company"))
            if not company:
                continue
            key = norm_key(row.get("website"), company)
            m = merged.setdefault(
                key,
                {
                    "Company": company,
                    "Website": _s(row.get("website")),
                    "Roles": _s(row.get("roles")),
                    "Location": _s(row.get("location")),
                    "Signal": _s(row.get("signal")),
                    "Source URL": _s(row.get("source_url")),
                    "Found By": set(),
                },
            )
            m["Found By"].add(name)
            for col, k in (("Website", "website"), ("Source URL", "source_url"),
                           ("Location", "location"), ("Signal", "signal")):
                if not m[col] and row.get(k):
                    m[col] = _s(row.get(k))

    rows_out = []
    for m in merged.values():
        m["Found By"] = ",".join(sorted(m["Found By"]))
        rows_out.append(m)
    rows_out.sort(key=lambda r: (-len(r["Found By"].split(",")), r["Company"].lower()))

    cols = ["Company", "Website", "Roles", "Location", "Signal", "Source URL", "Found By"]
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows_out)

    print("\n[discovery] per-worker parsed: " + ", ".join(f"{k}={len(v)}" for k, v in results.items()))
    print(f"[discovery] merged unique companies: {len(rows_out)}  (elapsed {time.time()-t0:.1f}s)")
    print(f"[discovery] wrote {OUT}")
    for r in rows_out[:12]:
        print(f"  - {r['Company']} ({r['Website']}) [{r['Found By']}] {r['Signal']}")


if __name__ == "__main__":
    main()
