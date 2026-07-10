"""Weekly Buying-Intent Report generator.

Standalone revenue deliverable: aggregates funding + hiring signals from the
scraper suite, scores companies 0-100 on buying intent, and writes a
Markdown + CSV report under samples/. No Supabase, no LLM, no env vars —
runs on a bare clone:

    .venv/Scripts/python.exe report.py --days 7 --top 12 --out samples

Scraper modules are lazy-imported inside gather()/enrich() so this file (and
its tests) never require them at import time.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import inspect
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

logger = logging.getLogger("radar.report")

CSV_COLUMNS = [
    "Company",
    "Score",
    "Confidence",
    "Signals",
    "FundingDetail",
    "GTMOpenRoles",
    "LikelyNeed",
    "Domain",
    "SourceLinks",
    "SuggestedContactTitle",
    "SuggestedOpener",
]

_LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "plc", "gmbh", "sas", "bv", "ab", "oy", "srl", "pty",
}

_ENRICH_LIMIT = 50
_ENRICH_CONCURRENCY = 5


# --------------------------------------------------------------------------
# Gathering (lazy imports — sibling modules may be absent; each source is
# independently fault-tolerant so a missing scraper never kills the report)
# --------------------------------------------------------------------------

async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def gather(days: int) -> tuple[list[dict], list[dict]]:
    """Collect (funding_events, hiring_posts) from all available scrapers."""
    funding: list[dict] = []
    hiring: list[dict] = []

    try:
        from scrapers.funding_news import fetch_funding_events
        funding.extend(await _maybe_await(fetch_funding_events(days=days)) or [])
    except Exception as e:
        logger.error("funding_news unavailable/failed: %s", e)

    try:
        from scrapers.sec_edgar import fetch_form_d_filings
        funding.extend(await _maybe_await(fetch_form_d_filings(days=days)) or [])
    except Exception as e:
        logger.error("sec_edgar unavailable/failed: %s", e)

    try:
        from scrapers.hn_hiring import fetch_hiring_posts
        hiring.extend(await _maybe_await(fetch_hiring_posts()) or [])
    except Exception as e:
        logger.error("hn_hiring unavailable/failed: %s", e)

    logger.info("Gathered %d funding events, %d hiring posts", len(funding), len(hiring))
    return funding, hiring


# --------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------

def normalize_company(name: str) -> str:
    """Normalization key for grouping: lowercase, strip punctuation and
    trailing legal suffixes (Inc, LLC, Ltd, ...)."""
    tokens = re.sub(r"[^\w\s]", " ", (name or "").lower()).split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def merge_companies(funding: list[dict], hiring: list[dict]) -> list[dict]:
    """Group signals by normalized company name into candidate dicts."""
    by_key: dict[str, dict] = {}

    def slot(raw_name: str) -> dict | None:
        key = normalize_company(raw_name)
        if not key:
            return None
        if key not in by_key:
            by_key[key] = {
                "name": raw_name.strip(),
                "domain": None,
                "funding": [],
                "hiring": [],
            }
        return by_key[key]

    for event in funding:
        candidate = slot(event.get("company") or "")
        if candidate is not None:
            candidate["funding"].append(event)
    for post in hiring:
        candidate = slot(post.get("company") or "")
        if candidate is not None:
            candidate["hiring"].append(post)
    return list(by_key.values())


# --------------------------------------------------------------------------
# Enrichment (job boards; bounded concurrency, best-effort)
# --------------------------------------------------------------------------

async def enrich(candidates: list[dict], limit: int = _ENRICH_LIMIT,
                 concurrency: int = _ENRICH_CONCURRENCY) -> None:
    """Attach candidate['job_board'] for the top candidates by preliminary score."""
    try:
        from scrapers.job_boards import gtm_hiring_summary
    except Exception as e:
        logger.error("job_boards unavailable: %s", e)
        return

    try:
        from scrapers.funding_news import negative_signals
    except Exception:
        negative_signals = None

    top = rank_candidates(candidates)[:limit]
    sem = asyncio.Semaphore(concurrency)

    async def lookup(candidate: dict) -> None:
        async with sem:
            try:
                summary = await _maybe_await(gtm_hiring_summary(company=candidate["name"]))
                if summary:
                    candidate["job_board"] = summary
            except Exception as e:
                logger.warning("job board lookup failed for %s: %s", candidate["name"], e)
            if negative_signals is not None:
                try:
                    negatives = await _maybe_await(negative_signals(candidate["name"]))
                    if negatives:
                        candidate["negative_news"] = negatives
                except Exception as e:
                    logger.warning("negative-news check failed for %s: %s", candidate["name"], e)

    await asyncio.gather(*(lookup(c) for c in top))


# --------------------------------------------------------------------------
# Scoring (pure)
# --------------------------------------------------------------------------

def _is_sweet_spot_round(round_type) -> bool:
    r = str(round_type or "").strip().lower()
    return bool(r) and ("seed" in r or "series a" in r)


def _is_series_b(round_type) -> bool:
    return "series b" in str(round_type or "").strip().lower()


_EXEC_ROLE_KEYWORDS = ("head of sales", "head of revenue", "vp of sales", "vp sales",
                       "chief revenue", "cro", "vp of marketing", "vp marketing", "cmo")
_HIGH_INTENT_KEYWORDS = ("account executive", "sdr", "sales development",
                         "revops", "revenue operations")


def _role_flags(job_board: dict) -> tuple[bool, bool]:
    """(has exec GTM role, has high-intent role) from the roles list."""
    roles = [str(r).lower() for r in job_board.get("roles") or []]
    has_exec = any(kw in role for role in roles for kw in _EXEC_ROLE_KEYWORDS)
    has_high_intent = any(kw in role for role in roles for kw in _HIGH_INTENT_KEYWORDS)
    return has_exec, has_high_intent


def rank_candidates(candidates: list[dict]) -> list[dict]:
    """Score-desc ordering; ties broken by raise size (more budget first),
    then name — never by alphabet alone."""
    def key(c: dict):
        best = _best_funding(c) or {}
        return (
            -(c.get("score") if c.get("score") is not None else score_company(c)),
            -(best.get("amount_millions") or 0),
            (c.get("name") or "").lower(),
        )
    return sorted(candidates, key=key)


def score_company(candidate: dict) -> int:
    """Pure 0-100 buying-intent score, weighted per signal quality.

    Funding: +30 base, +10 amount sweet spot ($3-100M — enough budget to buy
    services, not so much that vendor relationships are locked), +10 for
    seed/Series A (+5 Series B). Job board: +15 any GTM opening, +5 at 3+,
    +10 for a revenue-leadership opening, +5 for AE/SDR/RevOps. HN post: +10,
    +5 with GTM roles. Multi-signal +15. Layoffs/hiring-freeze news -30.
    """
    score = 0
    funding = candidate.get("funding") or []
    hiring = candidate.get("hiring") or []
    job_board = candidate.get("job_board") or {}
    gtm_jobs = job_board.get("gtm_jobs") or 0

    if funding:
        score += 30
        if any(3 <= (ev.get("amount_millions") or 0) < 100 for ev in funding):
            score += 10
        if any(_is_sweet_spot_round(ev.get("round_type")) for ev in funding):
            score += 10
        elif any(_is_series_b(ev.get("round_type")) for ev in funding):
            score += 5
    if gtm_jobs > 0:
        score += 15
        if gtm_jobs >= 3:
            score += 5
        has_exec, has_high_intent = _role_flags(job_board)
        if has_exec:
            score += 10
        if has_high_intent:
            score += 5
    if hiring:
        score += 10
        if any(post.get("has_gtm_roles") for post in hiring):
            score += 5
    if funding and (hiring or gtm_jobs > 0):
        score += 15  # signals landing together is the strongest tell
    if candidate.get("negative_news"):
        score -= 30  # layoffs / hiring freeze close the buying window
    return max(0, min(100, score))


def likely_need(candidate: dict) -> str:
    """What this company probably needs from an outside agency right now."""
    job_board = candidate.get("job_board") or {}
    gtm_jobs = job_board.get("gtm_jobs") or 0
    has_exec, has_high_intent = _role_flags(job_board)
    funded = bool(candidate.get("funding"))
    hn = bool(candidate.get("hiring"))

    if has_exec:
        return ("Standing up revenue leadership — receptive to RevOps, CRM and "
                "outbound infrastructure before the new leader's first quarter ends.")
    if has_high_intent:
        return ("Scaling outbound — needs pipeline, lead data and sales automation "
                "while the new reps ramp.")
    if gtm_jobs > 0:
        return ("Growing the GTM team — demand gen, content and marketing "
                "automation services fit this stage.")
    if funded and not hn:
        return ("Fresh budget with no GTM hires posted yet — outside help bridges "
                "the gap this quarter.")
    if hn:
        return ("Hiring on a lean budget via HN — an automation-over-headcount "
                "pitch fits.")
    return "Early growth signals — worth light-touch monitoring."


# --------------------------------------------------------------------------
# Narrative templates (pure — built from actual signal facts)
# --------------------------------------------------------------------------

def _parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    try:
        return parsedate_to_datetime(s)  # RFC-822 (RSS pubDate)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fmt_date(raw) -> str:
    dt = _parse_dt(raw)
    return f"{dt:%b} {dt.day}" if dt else ""


def confidence_label(score: int) -> str:
    """Customers buy confidence, not scores: High / Medium / Low."""
    if score >= 70:
        return "High"
    if score >= 45:
        return "Medium"
    return "Low"


def outreach_window(candidate: dict, now: datetime | None = None) -> str:
    """How soon to reach out: fresh funding means the budget window is open."""
    now = now or datetime.now(timezone.utc)
    best = _best_funding(candidate)
    if best:
        dt = _parse_dt(best.get("published_at") or best.get("filed_at"))
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (now - dt).days <= 10:
                return "within 14 days — budget decisions are being made now"
    return "within 30 days"


def _fmt_amount(amount_millions: float) -> str:
    if amount_millions >= 1000:
        return f"${amount_millions / 1000:.1f}B".replace(".0B", "B")
    if amount_millions >= 1:
        return f"${amount_millions:.1f}M".replace(".0M", "M")
    return f"${amount_millions * 1000:.0f}K"


def _fmt_round(round_type) -> str:
    r = str(round_type or "").strip()
    if not r or r.lower() == "unknown":
        return ""
    return " ".join(w.upper() if len(w) == 1 else w.capitalize() for w in r.split())


def _best_funding(candidate: dict) -> dict | None:
    funding = candidate.get("funding") or []
    if not funding:
        return None
    return max(funding, key=lambda ev: ev.get("amount_millions") or 0)


def _funding_phrase(event: dict) -> str:
    amount = event.get("amount_millions") or 0
    rnd = _fmt_round(event.get("round_type"))
    date = _fmt_date(event.get("published_at") or event.get("filed_at"))
    phrase = "Raised"
    if amount:
        phrase += f" {_fmt_amount(amount)}"
    if rnd:
        phrase += f" {rnd}"
    if not amount and not rnd:
        phrase += " new funding"
    if date:
        phrase += f" on {date}"
    return phrase


def _hn_roles(candidate: dict) -> list[str]:
    roles: list[str] = []
    for post in candidate.get("hiring") or []:
        for role in post.get("roles") or []:
            if role not in roles:
                roles.append(role)
    return roles


def _join_roles(roles: list[str], limit: int = 3) -> str:
    return ", ".join(roles[:limit])


def why_now(candidate: dict) -> str:
    """One-sentence 'why this company, why this week' built from signal facts."""
    facts: list[str] = []
    best = _best_funding(candidate)
    if best:
        facts.append(_funding_phrase(best))

    job_board = candidate.get("job_board") or {}
    gtm_jobs = job_board.get("gtm_jobs") or 0
    if gtm_jobs:
        facts.append(f"has {gtm_jobs} open GTM role{'s' if gtm_jobs != 1 else ''}")
    else:
        roles = _hn_roles(candidate)
        if roles:
            facts.append(f"is hiring {_join_roles(roles)} on Hacker News")
        elif candidate.get("hiring"):
            facts.append("posted in the latest HN Who is hiring thread")

    has_hiring_signal = bool(gtm_jobs or candidate.get("hiring"))
    if best and has_hiring_signal:
        tail = " — budget and headcount are landing now."
    elif best:
        tail = " — new budget is typically allocated within the first 90 days."
    elif has_hiring_signal:
        tail = " — the revenue team is scaling and needs pipeline."
    else:
        return "Showing early buying-intent signals worth monitoring."
    return " and ".join(facts) + tail


def suggested_opener(candidate: dict) -> str:
    """One personalized cold-email first line referencing the actual signals."""
    name = candidate.get("name") or "your company"
    best = _best_funding(candidate)
    job_board = candidate.get("job_board") or {}
    gtm_jobs = job_board.get("gtm_jobs") or 0
    roles = list(job_board.get("roles") or []) or _hn_roles(candidate)
    role = roles[0] if roles else ""

    if best:
        amount = best.get("amount_millions") or 0
        rnd = _fmt_round(best.get("round_type"))
        if amount and rnd:
            raise_bit = f"the {_fmt_amount(amount)} {rnd}"
        elif amount:
            raise_bit = f"the {_fmt_amount(amount)} raise"
        elif rnd:
            raise_bit = f"the {rnd}"
        else:
            raise_bit = "the recent raise"
        if role:
            return (
                f"Congrats on {raise_bit} — noticed you're already hiring for "
                f"{role}, which usually means pipeline targets just went up."
            )
        if gtm_jobs:
            return (
                f"Congrats on {raise_bit} — saw you've opened {gtm_jobs} go-to-market "
                f"roles, which usually means pipeline targets just went up."
            )
        return (
            f"Congrats on {raise_bit} — most teams put new budget to work on "
            f"pipeline within the first 90 days, so the timing felt right to reach out."
        )
    if role:
        return (
            f"Noticed {name} is hiring a {role} — usually a sign pipeline targets "
            f"are climbing faster than the team can cover."
        )
    if gtm_jobs:
        return (
            f"Noticed {name} has {gtm_jobs} open go-to-market roles — usually a "
            f"sign pipeline targets are climbing."
        )
    return f"Been tracking {name}'s momentum and figured it was worth reaching out."


def suggested_contact_title(candidate: dict) -> str:
    job_board = candidate.get("job_board") or {}
    has_gtm = (job_board.get("gtm_jobs") or 0) > 0 or any(
        post.get("has_gtm_roles") for post in candidate.get("hiring") or []
    )
    if has_gtm:
        return "Head of Sales / Head of Growth"
    if candidate.get("funding"):
        return "Founder / CEO"
    return "Head of Marketing"


# --------------------------------------------------------------------------
# Rendering (pure; generated_on injected for deterministic tests)
# --------------------------------------------------------------------------

def _signal_bullets(entry: dict) -> list[str]:
    """Evidence trail: every ranking reason, checkable via its source link."""
    bullets: list[str] = []
    for event in entry.get("funding") or []:
        url = event.get("source_url") or ""
        source = event.get("source_name") or (
            "SEC EDGAR" if "sec.gov" in url else "source"
        )
        detail = event.get("detail") or _funding_phrase(event)
        bullets.append(f"✓ **Funding:** {detail}" + (f" ([{source}]({url}))" if url else ""))

    job_board = entry.get("job_board") or {}
    gtm_jobs = job_board.get("gtm_jobs") or 0
    if gtm_jobs:
        text = f"✓ **GTM hiring:** {gtm_jobs} open go-to-market role{'s' if gtm_jobs != 1 else ''}"
        roles = _join_roles(job_board.get("roles") or [])
        if roles:
            text += f" — {roles}"
        careers = job_board.get("careers_url")
        if careers:
            text += f" ([careers]({careers}))"
        bullets.append(text)

    for post in entry.get("hiring") or []:
        detail = post.get("detail") or "Hiring post"
        url = post.get("source_url") or ""
        bullets.append(f"✓ **HN hiring:** {detail}" + (f" ([post]({url}))" if url else ""))

    negatives = entry.get("negative_news") or []
    if negatives:
        first = negatives[0]
        url = first.get("source_url") or ""
        bullets.append(
            f"⚠ **Layoff check:** recent layoffs/hiring-freeze reported — approach with caution"
            + (f" ([source]({url}))" if url else "")
        )
    else:
        bullets.append("✓ **Layoff check:** none detected in the last 90 days of news")

    return bullets


def _contact_line(entry: dict) -> str:
    title = suggested_contact_title(entry)
    careers = (entry.get("job_board") or {}).get("careers_url")
    if careers:
        return f"{title} — see [careers page]({careers})"
    return title


def render_markdown(entries: list[dict], generated_on: str) -> str:
    lines = [
        "# AI Opportunity Radar — Weekly Buying-Intent Report",
        "",
        f"**Date:** {generated_on}",
        "",
        f"{len(entries)} companies showing fresh buying-intent signals this week. "
        "Recent funding and go-to-market hiring are the two strongest predictors "
        "of near-term spend on sales and marketing services.",
        "",
    ]
    for i, entry in enumerate(entries, 1):
        rank = entry.get("rank", i)
        score = entry.get("score", score_company(entry))
        confidence = entry.get("confidence") or confidence_label(score)
        lines.append(f"## {rank}. {entry.get('name', 'Unknown')} — {confidence} confidence")
        lines.append("")
        lines.extend(f"- {bullet}" for bullet in _signal_bullets(entry))
        lines.append("")
        lines.append(f"**Why now:** {entry.get('why_now') or why_now(entry)}")
        lines.append("")
        lines.append(f"**Likely need:** {entry.get('likely_need') or likely_need(entry)}")
        lines.append("")
        lines.append(f"**Recommended outreach:** {entry.get('outreach_window') or outreach_window(entry)}")
        lines.append("")
        lines.append(f"**Who to contact:** {_contact_line(entry)}")
        lines.append("")
        opener = entry.get("opener") or suggested_opener(entry)
        lines.append(f'**Suggested opener:** "{opener}"')
        lines.append("")
    lines += [
        "---",
        "",
        "## Methodology",
        "",
        "Companies are scored 0-100 across weighted signals: recent funding "
        "(base 30, +10 for the $3-100M sweet spot — enough budget to buy "
        "services, not so much that vendors are locked in — and +10 for "
        "seed/Series A), open go-to-market roles on public job boards (+15, "
        "with extra weight for revenue-leadership and AE/SDR/RevOps openings), "
        "Hacker News 'Who is hiring' posts, and a +15 multi-signal bonus when "
        "funding and hiring land in the same window. Companies with recent "
        "layoffs or a hiring freeze are penalized -30 — a closed buying window.",
        "",
        "Sources: Google News, Crunchbase News, TechCrunch, SEC EDGAR Form D "
        "filings, Hacker News 'Who is hiring' threads, and public ATS job "
        "boards (Greenhouse/Lever).",
        "",
        "*Generated by AI Opportunity Radar*",
        "",
    ]
    return "\n".join(lines)


def render_csv_rows(entries: list[dict]) -> list[dict]:
    rows = []
    for entry in entries:
        job_board = entry.get("job_board") or {}
        signals = []
        if entry.get("funding"):
            signals.append("funding")
        if job_board.get("gtm_jobs"):
            signals.append("gtm_hiring")
        if entry.get("hiring"):
            signals.append("hn_hiring")

        links: list[str] = []
        for record in (entry.get("funding") or []) + (entry.get("hiring") or []):
            url = record.get("source_url")
            if url and url not in links:
                links.append(url)
        careers = job_board.get("careers_url")
        if careers and careers not in links:
            links.append(careers)

        funding_events = entry.get("funding") or []
        score = entry.get("score", score_company(entry))
        rows.append({
            "Company": entry.get("name", ""),
            "Score": score,
            "Confidence": entry.get("confidence") or confidence_label(score),
            "Signals": "; ".join(signals),
            "FundingDetail": funding_events[0].get("detail", "") if funding_events else "",
            "GTMOpenRoles": job_board.get("gtm_jobs") or 0,
            "LikelyNeed": entry.get("likely_need") or likely_need(entry),
            "Domain": entry.get("domain") or "",
            "SourceLinks": " ".join(links),
            "SuggestedContactTitle": suggested_contact_title(entry),
            "SuggestedOpener": entry.get("opener") or suggested_opener(entry),
        })
    return rows


TRACKING_COLUMNS = [
    "Company", "ReportDate", "Signals", "Confidence",
    "AgencyContacted", "Reply", "Meeting", "ClosedDeal",
]


def append_tracking(entries: list[dict], path: Path | str, report_date: str) -> None:
    """Append this report's companies to the outcome log (idempotent per
    company+date). Once ~50-100 outreach outcomes are filled in, scoring
    weights can become evidence-based instead of argued."""
    path = Path(path)
    seen: set[tuple[str, str]] = set()
    if path.exists():
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                seen.add((row.get("Company", ""), row.get("ReportDate", "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TRACKING_COLUMNS)
        if write_header:
            writer.writeheader()
        for entry in entries:
            name = entry.get("name", "")
            if not name or (name, report_date) in seen:
                continue
            score = entry.get("score", score_company(entry))
            signals = []
            if entry.get("funding"):
                signals.append("funding")
            if (entry.get("job_board") or {}).get("gtm_jobs"):
                signals.append("gtm_hiring")
            if entry.get("hiring"):
                signals.append("hn_hiring")
            if entry.get("negative_news"):
                signals.append("negative_news")
            writer.writerow({
                "Company": name,
                "ReportDate": report_date,
                "Signals": "; ".join(signals),
                "Confidence": entry.get("confidence") or confidence_label(score),
                "AgencyContacted": "",
                "Reply": "",
                "Meeting": "",
                "ClosedDeal": "",
            })


def write_report(entries: list[dict], out_dir: str, generated_on: str) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / f"intent_report_{generated_on}.md"
    csv_path = out / f"intent_report_{generated_on}.csv"

    md_path.write_text(render_markdown(entries, generated_on), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(render_csv_rows(entries))
    return md_path, csv_path


# --------------------------------------------------------------------------
# Pipeline + CLI
# --------------------------------------------------------------------------

async def build_report(days: int = 7, top: int = 12) -> list[dict]:
    funding, hiring = await gather(days)
    candidates = merge_companies(funding, hiring)
    await enrich(candidates)
    for candidate in candidates:
        candidate["score"] = score_company(candidate)
    entries = rank_candidates(candidates)[:top]
    for rank, entry in enumerate(entries, 1):
        entry["rank"] = rank
        entry["confidence"] = confidence_label(entry["score"])
        entry["why_now"] = why_now(entry)
        entry["likely_need"] = likely_need(entry)
        entry["outreach_window"] = outreach_window(entry)
        entry["opener"] = suggested_opener(entry)
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the weekly Buying-Intent Report.")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days")
    parser.add_argument("--top", type=int, default=12, help="Number of companies in the report")
    parser.add_argument("--out", default="samples", help="Output directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    entries = asyncio.run(build_report(days=args.days, top=args.top))
    if not entries:
        logger.warning("No candidates found — writing an empty report.")

    generated_on = datetime.now().strftime("%Y-%m-%d")
    md_path, csv_path = write_report(entries, args.out, generated_on)
    tracking_path = Path(args.out) / "tracking.csv"
    append_tracking(entries, tracking_path, generated_on)
    print(f"Wrote {md_path} and {csv_path} ({len(entries)} companies)")
    print(f"Outcome log: {tracking_path} — fill in Reply/Meeting/ClosedDeal as outreach lands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
