#!/usr/bin/env python
"""Phase 2.5 - JOIN validator output with worker provenance -> final_records.json.

The validation workflow (validate_workflow.js) returns authoritative, web-checked
company records. This step:
  - attaches provenance (found_by / found_count / segments) from unified_candidates.json
  - backfills low-risk channels (careers_url, linkedin_url, apply_url, website) when
    the validator left them empty, using what the workers found
  - re-includes any candidate the validator dropped (batch failure) so nothing is lost

Run:  python discovery/finalize.py <validator_output.json> [unified_candidates.json]
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
    v = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(v, dict):
        v = v.get("companies") or v.get("records") or []
    return v if isinstance(v, list) else []


def main():
    if len(sys.argv) < 2:
        print("usage: python discovery/finalize.py <validator_output.json> [unified_candidates.json]")
        sys.exit(1)
    validated = load(Path(sys.argv[1]))
    uni_path = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "unified_candidates.json"
    unified = load(uni_path)

    prov = {}
    for c in unified:
        prov[norm_key(c.get("website") or c.get("domain"), c.get("company"))] = c

    out = {}
    for v in validated:
        company = _s(v.get("company"))
        if not company:
            continue
        key = norm_key(v.get("domain") or v.get("website"), company)
        rec = dict(v)
        src = prov.get(key, {})
        rec["found_by"] = src.get("found_by") or v.get("found_by") or []
        rec["found_count"] = src.get("found_count") or 1
        rec["segments"] = src.get("segments") or []
        # backfill low-risk channels from worker data when validator is empty
        for fld in ("careers_url", "linkedin_url", "apply_url", "website", "source_url"):
            if not _s(rec.get(fld)) and _s(src.get(fld)):
                rec[fld] = src.get(fld)
        out[key] = rec

    # re-include candidates the validator dropped entirely
    readded = 0
    for key, c in prov.items():
        if key in out:
            continue
        readded += 1
        out[key] = {
            "company": c.get("company"),
            "domain": key,
            "website": c.get("website"),
            "careers_url": c.get("careers_url"),
            "application_email": c.get("application_email"),
            "contact_email": c.get("contact_email"),
            "linkedin_url": c.get("linkedin_url"),
            "apply_url": c.get("apply_url"),
            "source_url": c.get("source_url"),
            "signal": c.get("signal"),
            "positions": c.get("positions") or [],
            "verified": False,
            "verification_status": "not_processed",
            "junior_roles_open": None,
            "found_by": c.get("found_by") or [],
            "found_count": c.get("found_count") or 1,
            "segments": c.get("segments") or [],
        }

    records = list(out.values())
    dst = HERE / "final_records.json"
    dst.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    verified = sum(1 for r in records if r.get("verified"))
    junior = sum(1 for r in records if r.get("junior_roles_open") is True)
    pos = sum(len(r.get("positions") or []) for r in records)
    print(f"[finalize] validated={len(validated)} unified={len(unified)} re-added={readded}")
    print(f"[finalize] final companies={len(records)} verified={verified} junior_hiring={junior} positions={pos}")
    print(f"[finalize] wrote {dst}")


if __name__ == "__main__":
    main()
