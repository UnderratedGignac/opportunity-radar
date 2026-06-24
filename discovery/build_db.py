#!/usr/bin/env python
"""Phase 3 - DATABASE. Build/refresh discovery/prospects.db from a records JSON.

Relational schema designed for an auto-apply agent:
  companies(domain unique) -- who to apply to + how (careers_url, apply email, ATS)
  positions(company_id FK) -- the actual open AI/SWE roles + apply URLs
  runs                     -- provenance of each research+validation run

Upserts companies by normalized domain (merges found_by, fills blanks, refreshes
validation + last_seen). Positions deduped by (company_id, title, job_url).
Also exports companies.csv and positions.csv next to the DB.

Run:  python discovery/build_db.py <records.json> [run_id]
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "prospects.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT NOT NULL,
  domain TEXT UNIQUE,
  website TEXT,
  careers_url TEXT,
  ats_platform TEXT,
  application_email TEXT,
  contact_email TEXT,
  contact_page_url TEXT,
  linkedin_url TEXT,
  location TEXT,
  signal TEXT,
  junior_hiring INTEGER DEFAULT -1,     -- 1 junior/entry roles open, 0 none, -1 unknown
  found_by TEXT,
  segments TEXT,
  found_count INTEGER DEFAULT 1,
  verified INTEGER DEFAULT -1,          -- 1 hiring confirmed, 0 not, -1 unknown
  verification_status TEXT,
  evidence_url TEXT,
  verification_notes TEXT,
  confidence REAL,
  source_url TEXT,
  first_seen TEXT,
  last_seen TEXT,
  run_id TEXT
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  title TEXT,
  level TEXT,
  location TEXT,
  job_url TEXT,
  apply_url TEXT,
  employment_type TEXT,
  posted_date TEXT,
  description_snippet TEXT,
  source TEXT,
  scraped_at TEXT,
  UNIQUE(company_id, title, job_url)
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT,
  n_input INTEGER,
  n_companies INTEGER,
  n_positions INTEGER,
  n_verified INTEGER,
  workers_used TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_companies_verified ON companies(verified);
CREATE INDEX IF NOT EXISTS idx_positions_company ON positions(company_id);
"""


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).strip()


def norm_domain(website, company) -> str:
    if website:
        d = str(website).strip().lower()
        d = re.sub(r"^https?://", "", d)
        d = re.sub(r"^www\.", "", d)
        d = d.split("/")[0].strip()
        if d:
            return d
    return (company or "").strip().lower()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def positions_of(rec) -> list[dict]:
    out = []
    for p in rec.get("positions") or []:
        if not isinstance(p, dict):
            continue
        out.append(
            {
                "title": _s(p.get("title")),
                "level": _s(p.get("level")),
                "location": _s(p.get("location")),
                "job_url": _s(p.get("job_url") or p.get("url")),
                "apply_url": _s(p.get("apply_url")),
                "employment_type": _s(p.get("employment_type")),
                "posted_date": _s(p.get("posted_date")),
                "description_snippet": _s(p.get("description_snippet") or p.get("description"))[:500],
                "source": _s(p.get("source") or p.get("source_url")),
            }
        )
    return [p for p in out if p["title"]]


def verified_int(rec) -> int:
    v = rec.get("verified")
    if isinstance(v, bool):
        return 1 if v else 0
    status = _s(rec.get("verification_status")).lower()
    if status in ("verified", "verified_hiring", "confirmed", "hiring"):
        return 1
    if status in ("not_hiring", "not_found", "unreachable", "false"):
        return 0
    return -1


def main():
    if len(sys.argv) < 2:
        print("usage: python discovery/build_db.py <records.json> [run_id]")
        sys.exit(1)
    src = Path(sys.argv[1])
    run_id = sys.argv[2] if len(sys.argv) > 2 else "run_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    records = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(records, dict):
        records = records.get("companies") or records.get("records") or [records]

    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    cur = conn.cursor()
    ts = now_iso()

    n_pos = 0
    workers = set()
    for rec in records:
        company = _s(rec.get("company"))
        if not company:
            continue
        domain = norm_domain(rec.get("website") or rec.get("domain"), company)
        found_by = rec.get("found_by") or []
        if isinstance(found_by, str):
            found_by = [found_by]
        workers.update(found_by)
        fields = {
            "company": company,
            "domain": domain,
            "website": _s(rec.get("website")),
            "careers_url": _s(rec.get("careers_url")),
            "ats_platform": _s(rec.get("ats_platform")),
            "application_email": _s(rec.get("application_email")),
            "contact_email": _s(rec.get("contact_email")),
            "contact_page_url": _s(rec.get("contact_page_url")),
            "linkedin_url": _s(rec.get("linkedin_url")),
            "location": _s(rec.get("location")),
            "signal": _s(rec.get("signal")),
            "junior_hiring": (1 if rec.get("junior_roles_open") is True else (0 if rec.get("junior_roles_open") is False else -1)),
            "found_by": ",".join(sorted(set(found_by))),
            "segments": _s(rec.get("segments")),
            "found_count": int(rec.get("found_count") or 1),
            "verified": verified_int(rec),
            "verification_status": _s(rec.get("verification_status")),
            "evidence_url": _s(rec.get("evidence_url")),
            "verification_notes": _s(rec.get("verification_notes") or rec.get("notes"))[:600],
            "confidence": float(rec["confidence"]) if isinstance(rec.get("confidence"), (int, float)) else None,
            "source_url": _s(rec.get("source_url")),
            "run_id": run_id,
        }

        cur.execute("SELECT id, found_by, first_seen FROM companies WHERE domain=?", (domain,))
        existing = cur.fetchone()
        if existing:
            cid, old_found, first_seen = existing
            merged_found = ",".join(sorted(set((old_found or "").split(",")) | set(found_by) - {""}))
            sets = ", ".join(f"{k}=?" for k in fields if k not in ("company", "domain"))
            vals = [fields[k] for k in fields if k not in ("company", "domain")]
            cur.execute(
                f"UPDATE companies SET {sets}, found_by=?, last_seen=? WHERE id=?",
                vals + [merged_found, ts, cid],
            )
        else:
            cols = list(fields.keys()) + ["first_seen", "last_seen"]
            cur.execute(
                f"INSERT INTO companies ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                [fields[k] for k in fields] + [ts, ts],
            )
            cid = cur.lastrowid

        for p in positions_of(rec):
            try:
                cur.execute(
                    """INSERT OR IGNORE INTO positions
                       (company_id,title,level,location,job_url,apply_url,employment_type,posted_date,description_snippet,source,scraped_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, p["title"], p["level"], p["location"], p["job_url"], p["apply_url"],
                     p["employment_type"], p["posted_date"], p["description_snippet"], p["source"], ts),
                )
                n_pos += cur.rowcount
            except sqlite3.Error as e:
                print(f"  position insert skipped ({company}): {e}")

    n_companies = cur.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    n_verified = cur.execute("SELECT COUNT(*) FROM companies WHERE verified=1").fetchone()[0]
    n_positions_total = cur.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    cur.execute(
        "INSERT OR REPLACE INTO runs (run_id,started_at,n_input,n_companies,n_positions,n_verified,workers_used,notes) VALUES (?,?,?,?,?,?,?,?)",
        (run_id, ts, len(records), n_companies, n_positions_total, n_verified, ",".join(sorted(w for w in workers if w)), f"loaded from {src.name}"),
    )
    conn.commit()

    # exports
    comp_csv = HERE / "companies.csv"
    pos_csv = HERE / "positions.csv"
    comp_cols = ["company", "domain", "website", "careers_url", "ats_platform", "application_email",
                 "contact_email", "contact_page_url", "linkedin_url", "location", "signal",
                 "junior_hiring", "verified", "verification_status", "evidence_url",
                 "confidence", "found_by", "found_count", "source_url", "last_seen"]
    with open(comp_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(comp_cols)
        for row in cur.execute(f"SELECT {','.join(comp_cols)} FROM companies ORDER BY verified DESC, found_count DESC, company"):
            w.writerow(row)
    with open(pos_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["company", "title", "level", "location", "job_url", "apply_url", "employment_type", "posted_date", "source"])
        for row in cur.execute(
            """SELECT c.company,p.title,p.level,p.location,p.job_url,p.apply_url,p.employment_type,p.posted_date,p.source
               FROM positions p JOIN companies c ON c.id=p.company_id
               ORDER BY c.company,p.title"""
        ):
            w.writerow(row)

    conn.close()
    print(f"[db] run_id={run_id}")
    print(f"[db] companies={n_companies} (verified={n_verified})  positions={n_positions_total} (+{n_pos} new)")
    print(f"[db] wrote {DB}")
    print(f"[db] exported {comp_csv.name}, {pos_csv.name}")


if __name__ == "__main__":
    main()
