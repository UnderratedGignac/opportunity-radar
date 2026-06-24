"""Opportunity Radar configuration — loaded from environment variables."""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # AI (Google Gemini via AGY worker or OAuth Bearer token)
    GEMINI_ACCESS_TOKEN: str = os.getenv("GEMINI_ACCESS_TOKEN", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # Database (Supabase free tier)
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

    # Signal sources
    BING_API_KEY: str = os.getenv("BING_API_KEY", "")

    # Email notifications (Gmail SMTP — optional, free)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")
    FROM_EMAIL: str = os.getenv("FROM_EMAIL", "")

    # Billing (Stripe — free until you charge customers)
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_PILOT: str = os.getenv("STRIPE_PRICE_PILOT", "")
    STRIPE_PRICE_GROWTH: str = os.getenv("STRIPE_PRICE_GROWTH", "")
    STRIPE_PRICE_SCALE: str = os.getenv("STRIPE_PRICE_SCALE", "")

    # Pipeline
    PIPELINE_CONCURRENCY: int = int(os.getenv("PIPELINE_CONCURRENCY", "3"))
    MIN_SCORE_THRESHOLD: int = int(os.getenv("MIN_SCORE_THRESHOLD", "60"))

    # Agency profile (shown in outreach copy)
    AGENCY_NAME: str = os.getenv("AGENCY_NAME", "Your Agency")
    AGENCY_SPECIALTY: str = os.getenv("AGENCY_SPECIALTY", "AI automation for B2B companies")

    @classmethod
    def validate(cls) -> list[str]:
        missing = []
        if not cls.GEMINI_ACCESS_TOKEN and not cls.GEMINI_API_KEY:
            missing.append("GEMINI_ACCESS_TOKEN or GEMINI_API_KEY")
        if not cls.SUPABASE_URL:
            missing.append("SUPABASE_URL")
        if not cls.SUPABASE_KEY:
            missing.append("SUPABASE_KEY")
        return missing


settings = Settings()
