"""Response/persistence contracts for the Routing Optimization Agent
(PR4). Every field here is either a direct read of PR1-PR3 data or a
simple, deterministic derivation of it — see docs/pr4-routing-agent.md
for why no LLM is involved in producing these.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Evidence(BaseModel):
    """A pointer to the specific data a Finding is based on, plus the
    derived numbers that data produced — never a copy of the underlying
    row itself. `reference_id` lets a reader go look up the source
    (e.g. an optimization_recommendations.recommendation_id) directly."""

    reference_type: str
    reference_id: str | None
    description: str
    metrics: dict[str, float | int | str | None]


class Finding(BaseModel):
    finding_id: str
    category: str
    summary: str
    risk_level: str
    confidence: float
    evidence: list[Evidence]


class SuggestedAction(BaseModel):
    action: str
    rationale: str
    related_recommendation_id: str | None
    confidence: float


class InvestigationReport(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    report_id: str
    created_at: datetime
    policy_version: str
    executive_summary: str
    findings: list[Finding]
    suggested_actions: list[SuggestedAction]
    risk_level: str
    confidence: float

    # Observable operations only — never the agent's internal "reasoning",
    # since there isn't any: the pipeline is a fixed sequence of
    # deterministic queries, not an LLM call. See docs/pr4-routing-agent.md.
    investigation_steps: list[str]
    tools_used: list[str]


class InvestigationReportSummary(BaseModel):
    """Lightweight listing row for GET /agent/reports — full findings are
    only returned by GET /agent/report/{id}, so listing many reports
    doesn't mean pulling every finding for every one of them."""

    report_id: str
    created_at: datetime
    policy_version: str
    executive_summary: str
    risk_level: str
    confidence: float
