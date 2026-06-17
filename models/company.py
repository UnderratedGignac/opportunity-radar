"""Company profile model."""

from __future__ import annotations

from pydantic import BaseModel


class CompanyProfile(BaseModel):
    name: str
    domain: str
    industry: str | None = None
    employee_count: int | None = None
    revenue_range: str | None = None
    hq_city: str | None = None
    hq_country: str | None = None
    tech_stack: list[str] = []
    linkedin_url: str | None = None
    crunchbase_url: str | None = None
    business_model: str | None = None  # b2b | b2c | marketplace

    @property
    def fit_multiplier(self) -> float:
        """Company fit score multiplier for opportunity scoring (0.5–1.5)."""
        score = 1.0
        if self.employee_count:
            if 10 <= self.employee_count <= 200:
                score += 0.3
            elif 201 <= self.employee_count <= 500:
                score += 0.1
        if self.business_model == "b2b":
            score += 0.2
        industry_boost = {"saas", "software", "fintech", "healthtech", "ecommerce"}
        if self.industry and any(k in self.industry.lower() for k in industry_boost):
            score += 0.2
        has_automation = any(
            t.lower() in {"zapier", "make", "n8n", "hubspot", "salesforce"}
            for t in self.tech_stack
        )
        if has_automation:
            score += 0.15
        return min(1.5, max(0.5, score))
