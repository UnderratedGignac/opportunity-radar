#!/usr/bin/env python
"""Merge worker outputs into one deduped candidate set for validation.

Combines:
  discovery/candidates.json            (Qwen + Gemini, from research_workers.py)
  discovery/agy_work/agy_companies.json (AGY offline-knowledge list)
-> discovery/unified_candidates.json   (deduped by domain, provenance preserved)

Run:  python discovery/merge_candidates.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).strip()


def norm_key(website, company) -> str:
    if website:
        d = str(website).strip().lower()
        d = re.sub(r"^https?://", "", d)
        d = re.sub(r"^www\.", "", d)
        d = d.split("/")[0].strip()
        if d:
            return d
    return (company or "").strip().lower()


def load(p: Path):
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
        return v if isinstance(v, list) else []
    except Exception as e:  # noqa: BLE001
        print(f"  (could not load {p.name}: {e})")
        return []


def dedupe_positions(positions):
    seen, out = set(), []
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        title = _s(p.get("title"))
        if not title:
            continue
        url = _s(p.get("url") or p.get("job_url"))
        k = (title.lower(), url.lower())
        if k in seen:
            continue
        seen.add(k)
        out.append({"title": title, "location": _s(p.get("location")), "url": url})
    return out


def main():
    merged: dict[str, dict] = {}

    def add(row, default_worker=None):
        company = _s(row.get("company"))
        if not company:
            return
        key = norm_key(row.get("website"), company)
        m = merged.setdefault(
            key,
            {
                "company": company,
                "website": _s(row.get("website")),
                "careers_url": _s(row.get("careers_url")),
                "application_email": _s(row.get("application_email")),
                "apply_url": _s(row.get("apply_url")),
                "linkedin_url": _s(row.get("linkedin_url")),
                "contact_email": _s(row.get("contact_email")),
                "source_url": _s(row.get("source_url")),
                "signal": _s(row.get("signal")),
                "positions": [],
                "found_by": set(),
                "found_count": 0,
            },
        )
        fb = row.get("found_by")
        if isinstance(fb, str):
            fb = [fb]
        if not fb:
            fb = [default_worker] if default_worker else []
        m["found_by"].update(x for x in fb if x)
        m["found_count"] += int(row.get("found_count") or 1)
        for col, k in (("website", "website"), ("careers_url", "careers_url"),
                       ("application_email", "application_email"), ("apply_url", "apply_url"),
                       ("linkedin_url", "linkedin_url"), ("contact_email", "contact_email"),
                       ("source_url", "source_url"), ("signal", "signal")):
            if not m[col] and row.get(k):
                m[col] = _s(row.get(k))
        m["positions"] += row.get("positions") or []

    cands = load(HERE / "candidates.json")          # Qwen + Gemini (junior sweep)
    general = load(HERE / "candidates_general.json")  # preserved general AI/SWE sweep
    agy = load(HERE / "agy_work" / "agy_companies.json")  # AGY offline knowledge
    for r in cands:
        add(r)
    for r in general:
        add(r)
    for r in agy:
        add(r, default_worker="agy")

    out = []
    for m in merged.values():
        m["positions"] = dedupe_positions(m["positions"])
        m["found_by"] = sorted(m["found_by"])
        out.append(m)
    out.sort(key=lambda r: (-len(r["found_by"]), -r["found_count"], r["company"].lower()))

    dst = HERE / "unified_candidates.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    multi = sum(1 for r in out if len(r["found_by"]) > 1)
    print(f"[merge] junior={len(cands)} general={len(general)} agy={len(agy)} -> unified unique={len(out)} (multi-source={multi})")
    print(f"[merge] wrote {dst}")
    for r in out[:12]:
        print(f"  - {r['company']} ({r['website']}) [{','.join(r['found_by'])}] x{r['found_count']}")


if __name__ == "__main__":
    main()
