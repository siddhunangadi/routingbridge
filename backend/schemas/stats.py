"""Response shape for GET /stats — aggregate numbers for the dashboard."""

from pydantic import BaseModel


class StatsResponse(BaseModel):
    total_requests: int
    total_cost: float
    avg_latency_ms: float
    requests_per_tier: dict[str, int]
    cost_per_model: dict[str, float]
    estimated_savings: float
