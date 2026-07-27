"""The DecisionCard: a structured, deterministic explanation of one routing
decision, built entirely from what's already persisted (routing_decisions +
execution_results, plus a possible optimization_recommendations match).

No LLM is involved in producing a DecisionCard — every field and every
reasoning_steps entry is a direct read or simple derivation of columns
PR1/PR2 already write. See docs/pr3-decision-intelligence.md.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DecisionReason(BaseModel):
    """One ordered step in how a routing decision was reached."""

    step: int
    description: str


class RecommendationSummary(BaseModel):
    """The advisory alternative on record for this decision's
    (policy_version, task_type, task_subcategory, provider, model) — never
    applied, only surfaced. See routing_learning.py and
    docs/pr2-analytics.md for how it was generated."""

    model_config = ConfigDict(protected_namespaces=())

    recommendation_id: str
    recommended_provider: str
    recommended_model: str
    expected_cost_change: float
    expected_quality_change: float
    confidence: float
    summary: str


class DecisionCard(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    timestamp: datetime
    policy_version: str
    task_type: str
    task_subcategory: str | None
    selected_provider: str
    selected_model: str
    selected_tier: str
    routing_reason: list[str]
    estimated_cost: float
    estimated_latency_ms: float
    confidence: float
    reasoning_steps: list[DecisionReason]

    # Whether an optimization_recommendations row matches this decision's
    # (policy_version, task_type, task_subcategory, provider, model).
    # Never true because of anything routing.py did — recommendation_id,
    # when present, is a pointer for GET /routing/decision/{id} to also
    # return a RecommendationSummary. Routing itself is unaffected either way.
    recommendation_available: bool
    recommendation_id: str | None


class DecisionDetailResponse(BaseModel):
    """GET /routing/decision/{request_id} response: the card plus the full
    recommendation it points at, if any — the router/service resolve
    recommendation_id into this so a client never has to make a second call."""

    decision_card: DecisionCard
    recommendation: RecommendationSummary | None
