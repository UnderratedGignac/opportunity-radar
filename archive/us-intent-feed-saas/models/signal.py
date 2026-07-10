"""Signal and opportunity data models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SignalType(str, Enum):
    FUNDING = "funding"
    HIRING = "hiring"
    EXEC_CHANGE = "exec_change"
    TECH_CHANGE = "tech_change"
    WEBSITE_CHANGE = "website_change"
    NEWS = "news"


class Signal(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    company_domain: str
    signal_type: SignalType
    detail: str
    source_url: str | None = None
    source_type: str | None = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class ScoredSignal(BaseModel):
    signal: Signal
    base_weight: float
    recency_multiplier: float
    weighted_score: float


class Opportunity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    company_name: str
    company_domain: str
    opportunity_score: int = Field(ge=0, le=100)
    confidence_score: int = Field(ge=0, le=100)
    signals: list[ScoredSignal] = Field(default_factory=list)
    likely_needs: list[str] = Field(default_factory=list)
    decision_maker_titles: list[str] = Field(default_factory=list)
    timing_rationale: str = ""
    score_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None


class Contact(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    title: str
    email: str | None = None
    linkedin_url: str | None = None
    company_domain: str
    source: str = "apollo"


class OutreachPackage(BaseModel):
    opportunity: Opportunity
    contacts: list[Contact] = Field(default_factory=list)
    email_subject: str = ""
    email_body: str = ""
    linkedin_message: str = ""
    call_opener: str = ""
    key_hook: str = ""
