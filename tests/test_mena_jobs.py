"""Offline tests for scrapers/mena_jobs.py — LinkedIn-guest lead discovery."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.mena_jobs import (
    classify_automatable_role,
    company_website_from_linkedin,
    extract_company_industry,
    extract_company_size,
    find_leads,
    is_enterprise_by_size,
    is_low_value_company,
    is_software_company,
    parse_job_cards,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _jobs_html() -> str:
    return (FIXTURES / "mena_linkedin_jobs.html").read_text(encoding="utf-8")


def _company_html() -> str:
    return (FIXTURES / "mena_linkedin_company.html").read_text(encoding="utf-8")


def _software_company_html() -> str:
    return (FIXTURES / "mena_linkedin_company_software.html").read_text(encoding="utf-8")


def _enterprise_company_html() -> str:
    return (FIXTURES / "mena_linkedin_company_enterprise.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- parse_job_cards

def test_parse_job_cards_extracts_all_fields():
    cards = parse_job_cards(_jobs_html())
    assert len(cards) == 5
    c = cards[0]
    assert c["title"] == "Data Processor"
    assert c["company"] == "Unilabs Middle East"
    assert c["company_slug"] == "unilabsme"
    assert c["company_linkedin_url"] == "https://ae.linkedin.com/company/unilabsme"
    assert c["location"] == "Abu Dhabi, United Arab Emirates"
    assert c["country"] == "United Arab Emirates"
    assert "4436203263" in c["job_url"]


def test_parse_job_cards_unescapes_entities():
    cards = parse_job_cards(_jobs_html())
    admin = next(c for c in cards if c["company_slug"] == "abualnaga-contracting")
    assert admin["title"] == "Administrative Assistant & Booking Coordinator"


def test_parse_job_cards_flags_lebanon():
    cards = parse_job_cards(_jobs_html())
    leb = next(c for c in cards if c["company_slug"] == "core-code-io")
    assert leb["country"] == "Lebanon"
    assert leb["company_linkedin_url"].startswith("https://lb.linkedin.com")


# ---------------------------------------------------------------- classify role

def test_classify_automatable_roles():
    for title, cat in [
        ("Data Processor", "data_entry"),
        ("Data Entry Clerk - Immediately Available", "data_entry"),
        ("Administrative Assistant & Booking Coordinator", "booking"),
        ("Customer Support Agent", "support"),
        ("Junior Accountant / Data Entry", "finance"),
        ("Social Media Coordinator", "marketing"),
        ("Appointment Scheduling Coordinator", "booking"),
    ]:
        role = classify_automatable_role(title)
        assert role is not None, title
        assert role["category"] == cat
        assert role["pain"] and role["package"]


def test_classify_rejects_non_automatable():
    for title in ["Senior Drilling Engineer", "Chief Financial Officer",
                  "Mechanical Technician", "Registered Nurse"]:
        assert classify_automatable_role(title) is None, title


# ---------------------------------------------------------------- low-value filter

def test_is_low_value_company_flags_anonymous_and_agencies():
    assert is_low_value_company("Confidential Careers", "confidentialcareers") is True
    assert is_low_value_company("Michael Page", "michael-page") is True
    assert is_low_value_company("RTC-1 Employment Services", "rtc-1") is True
    # a real SMB is kept
    assert is_low_value_company("ABU ALNAGA CONTRACTING", "abualnaga-contracting") is False


def test_is_low_value_company_flags_known_enterprises():
    assert is_low_value_company("Saipem", "saipem") is True
    assert is_low_value_company("GEMS Education", "gems-education") is True


# ---------------------------------------------------------------- software-company filter ("skip LOGOS")

def test_extract_company_industry():
    assert extract_company_industry(_company_html()) == "Hospitals and Health Care"
    assert extract_company_industry(_software_company_html()) == "Computer Software"
    assert extract_company_industry("<html>no industry field</html>") is None


def test_is_software_company_by_industry():
    assert is_software_company("Logos Software Solutions", industry="Computer Software") is True
    assert is_software_company("Unilabs Middle East", industry="Hospitals and Health Care") is False
    for industry in ["Information Technology & Services", "Internet", "Computer Games",
                      "IT Services and IT Consulting", "SaaS"]:
        assert is_software_company("Some Co", industry=industry) is True, industry


def test_is_software_company_name_fallback_when_industry_unknown():
    # no industry data available -> fall back to name keywords
    assert is_software_company("Beirut Software House", industry=None) is True
    assert is_software_company("Beirut Digital Technologies", industry=None) is True
    assert is_software_company("Beirut Trading Company", industry=None) is False
    assert is_software_company("Al Fajer Travel & Tourism LLC", industry=None) is False


# ---------------------------------------------------------------- company-size filter (catches enterprises name-blocklists miss)

def test_extract_company_size():
    assert extract_company_size(_company_html()) == "201-500 employees"
    assert extract_company_size(_enterprise_company_html()) == "10,001+ employees"
    assert extract_company_size("<html>no size field</html>") is None


def test_is_enterprise_by_size():
    assert is_enterprise_by_size("10,001+ employees") is True
    assert is_enterprise_by_size("1,001-5,000 employees") is True
    assert is_enterprise_by_size("501-1,000 employees") is False  # borderline, kept
    assert is_enterprise_by_size("11-50 employees") is False
    assert is_enterprise_by_size("2-10 employees") is False
    assert is_enterprise_by_size(None) is False  # unknown size never excludes on its own


async def test_find_leads_excludes_software_companies():
    async def fake_fetch(session, url, chrome=False):
        if "seeMoreJobPostings" in url:
            return _jobs_html()
        if "logos" in url:
            return _software_company_html()
        if "/company/" in url:
            return _company_html()
        return None

    with patch("scrapers.mena_jobs._fetch_text", fake_fetch), \
         patch("scrapers.mena_jobs.classify_automatable_role",
               lambda title: {"category": "admin", "pain": "p", "package": "pkg"}):
        # inject a software-company card by patching parse_job_cards' source once
        with patch("scrapers.mena_jobs.parse_job_cards", lambda html: [
            {"title": "Admin Assistant", "company": "Logos Software Solutions",
             "company_slug": "logos-software", "company_linkedin_url": "https://ae.linkedin.com/company/logos",
             "location": "Dubai, United Arab Emirates", "country": "United Arab Emirates", "job_url": "https://x/1"},
        ]):
            leads = await find_leads(["admin"], ["United Arab Emirates"], per_search=5)
    assert leads == []


async def test_find_leads_excludes_enterprise_by_size():
    # a company that dodges every name-based blocklist (e.g. Kempinski Hotels)
    # must still be excluded once its LinkedIn "Company size" reveals 10,001+
    async def fake_fetch(session, url, chrome=False):
        if "seeMoreJobPostings" in url:
            return _jobs_html()
        if "/company/" in url:
            return _enterprise_company_html()
        return None

    with patch("scrapers.mena_jobs._fetch_text", fake_fetch), \
         patch("scrapers.mena_jobs.classify_automatable_role",
               lambda title: {"category": "admin", "pain": "p", "package": "pkg"}):
        with patch("scrapers.mena_jobs.parse_job_cards", lambda html: [
            {"title": "Spa Receptionist", "company": "Kempinski Hotels",
             "company_slug": "kempinski-hotels", "company_linkedin_url": "https://ae.linkedin.com/company/kempinski-hotels",
             "location": "Dubai, United Arab Emirates", "country": "United Arab Emirates", "job_url": "https://x/2"},
        ]):
            leads = await find_leads(["admin"], ["United Arab Emirates"], per_search=5)
    assert leads == []


# ---------------------------------------------------------------- website bridge

def test_company_website_from_linkedin_decodes_redirect():
    assert company_website_from_linkedin(_company_html()) == "unilabs.ae"


def test_company_website_none_when_absent():
    assert company_website_from_linkedin("<html><body>no website here</body></html>") is None


# ---------------------------------------------------------------- find_leads (mocked I/O)

async def test_find_leads_end_to_end_filters_and_enriches():
    async def fake_fetch(session, url, chrome=False):
        if "seeMoreJobPostings" in url:
            return _jobs_html()
        if "/company/" in url:
            return _company_html()
        return None

    with patch("scrapers.mena_jobs._fetch_text", fake_fetch):
        leads = await find_leads(["data entry"], ["United Arab Emirates"], per_search=25)

    names = {lead["company"] for lead in leads}
    # anonymous + enterprise dropped; automatable SMBs kept
    assert "Confidential Careers" not in names
    assert "Saipem" not in names
    assert "Unilabs Middle East" in names
    lead = next(l for l in leads if l["company"] == "Unilabs Middle East")
    assert lead["website"] == "unilabs.ae"
    assert lead["role_title"] == "Data Processor"
    assert lead["category"] == "data_entry"
    assert lead["country"] == "United Arab Emirates"
