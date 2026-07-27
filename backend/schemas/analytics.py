"""Response contracts for the /analytics/* endpoints.

Strongly typed where the shape is fixed (one stat row per provider/model/
task type/day); `dict[str, int]` only for tier_distribution, whose keys
are exactly the three known RoutingTier values — a dict there isn't
"stringly typed data", it's a fixed 3-key lookup the frontend already
expects from /stats' requests_per_tier.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ProviderStats(BaseModel):
    provider: str
    request_count: int
    average_cost: float
    average_latency_ms: float
    pass_rate: float | None


class ModelStats(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider: str
    model: str
    request_count: int
    average_cost: float
    average_latency_ms: float
    pass_rate: float | None


class TaskTypeStats(BaseModel):
    task_type: str
    request_count: int
    average_cost: float
    average_latency_ms: float
    pass_rate: float | None


class DailyMetric(BaseModel):
    day: date
    request_count: int
    total_cost: float
    average_latency_ms: float


class RoutingOverviewResponse(BaseModel):
    providers: list[ProviderStats]
    models: list[ModelStats]
    task_types: list[TaskTypeStats]
    tier_distribution: dict[str, int]
    daily_metrics: list[DailyMetric]


class RoutingPatternResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    task_type: str
    task_subcategory: str | None
    provider: str
    model: str
    tier: str
    policy_version: str
    sample_size: int
    average_cost: float
    average_latency: float
    pass_rate: float | None
    failure_rate: float | None
    last_updated: datetime


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    recommendation_id: str
    task_type: str
    task_subcategory: str | None
    policy_version: str
    current_provider: str
    recommended_provider: str
    current_model: str
    recommended_model: str
    expected_cost_change: float
    expected_quality_change: float
    confidence: float
    reason: str
    evidence: dict
    status: str
    created_at: datetime


class RefreshResult(BaseModel):
    patterns_updated: int
    recommendations_generated: int
