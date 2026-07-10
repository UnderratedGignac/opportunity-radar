#!/usr/bin/env python
"""Phase 1 - WORKER RESEARCH (JUNIOR software developer / engineer focus).

Drive the workers (Qwen + Gemini live web; AGY offline knowledge; MiniMax when
quota returns) to find companies hiring JUNIOR / entry-level / new-grad software
developers & engineers (incl. junior AI/ML), capturing as much apply-relevant
data as possible. Accumulate + dedupe -> discovery/candidates.json.

Authoritative validation + position/contact extraction happens in Phase 2
(validate_workflow.js); this phase casts a wide net for candidate companies.

Run:  python discovery/research_workers.py
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\Elie\.claude")
from tools.workers import agy, gemini, minimax, qwen  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
OUT = HERE / "candidates.json"
AGY_DIR = HERE / "agy_work"
AGY_OUT = AGY_DIR / "agy_companies.json"

BASE = """You have LIVE web access - USE it (search the web, open job boards, ATS pages and careers pages).
{segment}

Focus on JUNIOR / ENTRY-LEVEL / NEW-GRAD / ASSOCIATE roles (roughly 0-2 years experience) for
Software Engineers, Software Developers, and junior AI/ML Engineers. Skip senior/staff/principal roles.

Return about {n} REAL companies. For EACH company return an object with EXACTLY these keys:
  "company"           : official company name
  "website"           : primary domain like "acme.com" (or null)
  "careers_url"       : the company's careers / jobs page URL (or null)
  "positions"         : array of up to 5 OPEN junior/entry-level roles, each {{"title","location","url","level"}} (level e.g. "junior"/"entry"/"new-grad")
  "application_email" : recruiting/careers email (careers@/jobs@/talent@...) if you find one, else null
  "apply_url"         : a direct application link (ATS: greenhouse/lever/ashby/workday) if known, else null
  "linkedin_url"      : the company's LinkedIn jobs/company URL if known, else null
  "contact_email"     : any general contact email if visible, else null
  "source_url"        : URL where this was verified (job listing or careers page)
  "signal"            : short note, e.g. "hiring new-grad SWEs", "3 junior dev roles open"

Output ONLY a valid JSON array of these objects. No prose, no markdown fences.
Do NOT invent companies, positions, emails, or URLs - only include what you actually find."""

SEGMENTS = [
    "Find companies currently hiring JUNIOR or entry-level Software Engineers / Software Developers (0-2 years experience).",
    "Find companies with OPEN new-grad / recent-university-graduate software engineer roles right now.",
    "Find early-stage startups (seed to Series B) hiring their first junior software developers.",
    "Find companies hiring junior backend, frontend, or full-stack developers.",
    "Find companies hiring junior or entry-level AI / Machine Learning engineers.",
    "Find companies known for hiring coding-bootcamp graduates and career changers into junior developer roles.",
    "Find companies in San Francisco / Bay Area hiring junior software engineers.",
    "Find companies in New York, Boston, Austin, and Seattle hiring junior software developers.",
    "Find remote-first companies hiring junior / entry-level software engineers.",
    "Find European companies (London, Berlin, Amsterdam, Dublin) hiring junior software developers.",
    "Find Canadian (Toronto, Vancouver) and Indian (Bangalore, Hyderabad) companies hiring junior software engineers.",
    "Find fintech companies hiring junior software developers and engineers.",
    "Find healthtech / biotech companies hiring junior software engineers.",
    "Find gaming, e-commerce, media, or edtech companies hiring junior software developers.",
    "Find enterprise SaaS and developer-tools companies hiring associate / junior software engineers.",
    "Find big tech and large public tech companies with open new-grad / early-career software engineer positions.",
]
GEMINI_SEGMENTS = [SEGMENTS[0], SEGMENTS[1], SEGMENTS[4], SEGMENTS[6], SEGMENTS[8], SEGMENTS[12], SEGMENTS[15]]


def extract_json_array(text: str) -> list:
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


def _tag(rows, worker, seg):
    out = []
    for row in rows:
        if isinstance(row, dict) and _s(row.get("company")):
            row["_worker"] = worker
            row["_segment"] = seg
            out.append(row)
    return out


def run_qwen_segments(n=20):
    rows = []
    for i, seg in enumerate(SEGMENTS):
        try:
            r = qwen(BASE.format(segment=seg, n=n), timeout=170, web_search=True)
            got = extract_json_array(r.text) if r.ok else []
            print(f"[qwen {i+1}/{len(SEGMENTS)}] ok={r.ok} {r.timing_s:.0f}s got={len(got)}", flush=True)
            rows += _tag(got, "qwen", i)
        except Exception as e:  # noqa: BLE001
            print(f"[qwen {i+1}] EXC {e}", flush=True)
    return rows


def run_gemini_segments(n=8):
    rows = []
    for i, seg in enumerate(GEMINI_SEGMENTS):
        try:
            r = gemini(BASE.format(segment=seg, n=n), timeout=120)
            got = extract_json_array(r.text) if r.ok else []
            print(f"[gemini {i+1}/{len(GEMINI_SEGMENTS)}] ok={r.ok} {r.timing_s:.0f}s got={len(got)} err={r.error[:40]!r}", flush=True)
            rows += _tag(got, "gemini", i)
        except Exception as e:  # noqa: BLE001
            print(f"[gemini {i+1}] EXC {e}", flush=True)
    return rows


def try_minimax(n=15):
    rows = []
    try:
        r = minimax(BASE.format(segment=SEGMENTS[0], n=n), timeout=120)
        if not r.ok:
            print(f"[minimax] disabled: {r.error[:90]!r}", flush=True)
            return rows
        rows += _tag(extract_json_array(r.text), "minimax", 0)
        for i, seg in enumerate(SEGMENTS[1:7], start=1):
            r = minimax(BASE.format(segment=seg, n=n), timeout=180)
            got = extract_json_array(r.text) if r.ok else []
            print(f"[minimax {i}] ok={r.ok} got={len(got)}", flush=True)
            rows += _tag(got, "minimax", i)
    except Exception as e:  # noqa: BLE001
        print(f"[minimax] EXC {e}", flush=True)
    return rows


def run_agy(n=30):
    AGY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        AGY_OUT.unlink()
    except FileNotFoundError:
        pass
    task = (
        "You are a data-generation worker. You do NOT need the internet - use your own knowledge.\n\n"
        f"TASK: Produce a JSON dataset of about {n} REAL companies well known for hiring JUNIOR / entry-level / "
        "new-grad Software Engineers and Software Developers (e.g. big tech with new-grad programs, large tech "
        "employers, consultancies, and well-funded startups with early-career roles).\n\n"
        "Write the output as a RAW JSON array to this EXACT absolute file path (the folder already exists):\n"
        "  " + str(AGY_OUT).replace("\\", "/") + "\n\n"
        "Each element MUST be an object with keys: company, website, careers_url, "
        'positions (array of {"title","location","url","level"} for junior/new-grad roles), '
        "application_email, apply_url, linkedin_url, contact_email, source_url, signal. "
        "Use null for unknown fields. Only real companies; never fabricate emails/URLs (use null). "
        "Write ONLY that one file.\n\n"
        "VERIFICATION: after writing, report the absolute path, the count, and confirm valid JSON."
    )
    rows = []
    try:
        r = agy(task, timeout=240, cwd=str(AGY_DIR))
        if AGY_OUT.exists():
            try:
                rows = json.loads(AGY_OUT.read_text(encoding="utf-8"))
            except Exception:
                rows = []
        if not rows and r.ok:
            rows = extract_json_array(r.text)
        print(f"[agy] ok={r.ok} {r.timing_s:.0f}s rows={len(rows)} err={r.error[:60]!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[agy] EXC {e}", flush=True)
    return _tag(rows if isinstance(rows, list) else [], "agy", -1)


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
        out.append({"title": title, "location": _s(p.get("location")), "url": url, "level": _s(p.get("level"))})
    return out


def main():
    t0 = time.time()
    print("[research] JUNIOR sweep: qwen/gemini/agy in parallel; minimax probe...", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        fq = ex.submit(run_qwen_segments)
        fg = ex.submit(run_gemini_segments)
        fa = ex.submit(run_agy)
        fm = ex.submit(try_minimax)
        raw = []
        for f in (fq, fg, fa, fm):
            try:
                raw += f.result()
            except Exception as e:  # noqa: BLE001
                print(f"[research] worker thread error: {e}", flush=True)

    merged: dict[str, dict] = {}
    for row in raw:
        company = _s(row.get("company"))
        if not company:
            continue
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
                "segments": set(),
                "found_count": 0,
            },
        )
        m["found_by"].add(row.get("_worker", "?"))
        m["segments"].add(row.get("_segment", -1))
        m["found_count"] += 1
        for col, k in (("website", "website"), ("careers_url", "careers_url"),
                       ("application_email", "application_email"), ("apply_url", "apply_url"),
                       ("linkedin_url", "linkedin_url"), ("contact_email", "contact_email"),
                       ("source_url", "source_url"), ("signal", "signal")):
            if not m[col] and row.get(k):
                m[col] = _s(row.get(k))
        pos = row.get("positions")
        if isinstance(pos, list):
            m["positions"] += pos

    out = []
    for m in merged.values():
        m["positions"] = dedupe_positions(m["positions"])
        m["found_by"] = sorted(m["found_by"])
        m["segments"] = sorted(s for s in m["segments"] if isinstance(s, int))
        out.append(m)
    out.sort(key=lambda r: (-len(r["found_by"]), -r["found_count"], r["company"].lower()))

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    by_worker: dict[str, int] = {}
    for row in raw:
        by_worker[row.get("_worker", "?")] = by_worker.get(row.get("_worker", "?"), 0) + 1
    print("\n[research] raw rows by worker: " + ", ".join(f"{k}={v}" for k, v in sorted(by_worker.items())), flush=True)
    print(f"[research] unique candidate companies: {len(out)}  (elapsed {time.time()-t0:.0f}s)", flush=True)
    print(f"[research] wrote {OUT}", flush=True)
    for r in out[:15]:
        print(f"  - {r['company']} ({r['website']}) [{','.join(r['found_by'])}] pos={len(r['positions'])} {r['signal'][:40]}", flush=True)


if __name__ == "__main__":
    main()
