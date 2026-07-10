"""GTM-hiring signal scraper — Greenhouse / Lever / Ashby public job-board APIs.

All three ATSs expose keyless JSON endpoints per company board. We probe each
board with up to 3 slug candidates derived from the company name/domain and
stop at the first board that yields postings. Open sales/GTM roles are a
direct buying-intent signal (new budget, revenue push).

Replaces the dead Indeed RSS scraper (linkedin_jobs.py).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import aiohttp

logger = logging.getLogger("radar.scraper.job_boards")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OpportunityRadar/1.0; eliehaddadh1@gmail.com)"}
_TIMEOUT = aiohttp.ClientTimeout(total=8)

# keyword -> (signal_type, base_weight); longest matching keyword wins
_GTM_ROLES: dict[str, tuple[str, int]] = {
    "founding account executive": ("hiring", 32),
    "account executive": ("hiring", 25),
    "sales development": ("hiring", 28),
    "sdr": ("hiring", 28),
    "vp of sales": ("exec_change", 35),
    "vp sales": ("exec_change", 35),
    "head of sales": ("exec_change", 35),
    "head of revenue": ("exec_change", 35),
    "chief revenue": ("exec_change", 35),
    "vp of marketing": ("exec_change", 30),
    "vp marketing": ("exec_change", 30),
    "chief marketing officer": ("exec_change", 30),
    "sales manager": ("hiring", 24),
    "sales engineer": ("hiring", 22),
    "sales enablement": ("hiring", 20),
    "demand generation": ("hiring", 24),
    "revenue operations": ("hiring", 18),
    "revops": ("hiring", 18),
    "marketing manager": ("hiring", 22),
    "customer success": ("hiring", 20),
    "partnerships": ("hiring", 20),
    "gtm": ("hiring", 26),
    "growth": ("hiring", 22),
}


def slug_candidates(company: str, domain: str | None = None) -> list[str]:
    """Ordered board-slug guesses: domain stem, joined name, hyphenated name, first word."""
    candidates: list[str] = []
    if domain:
        stem = re.sub(r"^https?://", "", domain.strip().lower())
        stem = re.sub(r"^www\.", "", stem).split("/")[0].split(".")[0]
        if stem:
            candidates.append(stem)
    words = [re.sub(r"[^a-z0-9]", "", w) for w in (company or "").lower().split()]
    words = [w for w in words if w]
    if words:
        candidates.append("".join(words))
        candidates.append("-".join(words))
        candidates.append(words[0])
    deduped: list[str] = []
    for c in candidates:
        if c and c not in deduped:
            deduped.append(c)
    return deduped[:3]


def classify_gtm_role(title: str) -> dict | None:
    """Classify a job title as a GTM buying-intent role; longest keyword wins."""
    lower = (title or "").lower()
    if not lower.strip():
        return None
    best: tuple[str, str, int] | None = None
    for keyword, (sig_type, weight) in _GTM_ROLES.items():
        if keyword in lower and (best is None or len(keyword) > len(best[0])):
            best = (keyword, sig_type, weight)
    if best is None:
        return None
    _, sig_type, weight = best
    label = "GTM leadership role open" if sig_type == "exec_change" else "GTM hiring"
    return {
        "signal_type": sig_type,
        "detail": f"{label}: {title.strip()}",
        "base_weight": weight,
    }


# ── per-board parsing ─────────────────────────────────────────────────────────

def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_greenhouse(payload: dict) -> list[dict]:
    jobs = []
    for j in payload.get("jobs") or []:
        jobs.append({
            "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "published_at": _iso(j.get("first_published")),
        })
    return jobs


def _parse_lever(payload: list) -> list[dict]:
    jobs = []
    for p in payload or []:
        created = p.get("createdAt")
        published = (
            datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            if isinstance(created, (int, float))
            else None
        )
        jobs.append({
            "title": p.get("text", ""),
            "url": p.get("hostedUrl", ""),
            "published_at": published,
        })
    # Lever feeds are grouped by team, not sorted — newest first
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    jobs.sort(key=lambda j: j["published_at"] or epoch, reverse=True)
    return jobs


def _parse_ashby(payload: dict) -> list[dict]:
    jobs = []
    for j in payload.get("jobs") or []:
        if j.get("isListed") is False:
            continue
        jobs.append({
            "title": j.get("title", ""),
            "url": j.get("jobUrl", ""),
            "published_at": _iso(j.get("publishedAt")),
        })
    return jobs


_BOARDS: list[tuple[str, str, object]] = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", _parse_greenhouse),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json&limit=100", _parse_lever),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}", _parse_ashby),
]


async def _get_json(session: aiohttp.ClientSession, url: str) -> tuple[int, object | None]:
    try:
        async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                return resp.status, None
            return resp.status, await resp.json(content_type=None)
    except Exception as e:
        logger.debug("Board fetch failed %s: %s", url, e)
        return 0, None


async def _probe(company: str, domain: str | None) -> tuple[str, str, list[dict], object] | None:
    """Try each board with each slug candidate; first board with postings wins."""
    slugs = slug_candidates(company, domain)
    if not slugs:
        return None
    async with aiohttp.ClientSession() as session:
        for board, url_template, parse in _BOARDS:
            for slug in slugs:
                status, payload = await _get_json(session, url_template.format(slug=slug))
                if status != 200 or payload is None:
                    continue
                jobs = parse(payload)
                if jobs:
                    return board, slug, jobs, payload
    return None


_CAREERS_URLS = {
    "greenhouse": "https://boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
}


async def scan_company_jobs(
    company: str, domain: str | None = None, recent_days: int = 30
) -> list[dict]:
    """Recent GTM job postings for a company as canonical signal dicts."""
    try:
        hit = await _probe(company, domain)
    except Exception as e:
        logger.warning("Job-board probe failed for %s: %s", company, e)
        return []
    if hit is None:
        return []
    board, _slug, jobs, _payload = hit
    cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
    signals = []
    for job in jobs:
        role = classify_gtm_role(job["title"])
        if role is None:
            continue
        if job["published_at"] is not None and job["published_at"] < cutoff:
            continue
        signals.append({
            "signal_type": role["signal_type"],
            "detail": role["detail"],
            "source_url": job["url"],
            "confidence": 0.85,
            "base_weight": role["base_weight"],
            "company": company,
            "role_title": job["title"],
            "board": board,
        })
    return signals


async def gtm_hiring_summary(company: str, domain: str | None = None) -> dict:
    """Snapshot of a company's job board: {} if no board found."""
    try:
        hit = await _probe(company, domain)
    except Exception as e:
        logger.warning("Job-board summary failed for %s: %s", company, e)
        return {}
    if hit is None:
        return {}
    board, slug, jobs, payload = hit
    if board == "greenhouse":
        total = (payload.get("meta") or {}).get("total", len(jobs))
    else:
        total = len(jobs)
    gtm_count = 0
    gtm_titles: list[str] = []
    for j in jobs:
        if not classify_gtm_role(j["title"]):
            continue
        gtm_count += 1
        title = j["title"].strip()
        if title and title not in gtm_titles:
            gtm_titles.append(title)
    return {
        "board": board,
        "slug": slug,
        "total_jobs": total,
        "gtm_jobs": gtm_count,
        "roles": gtm_titles,
        "careers_url": _CAREERS_URLS[board].format(slug=slug),
    }
