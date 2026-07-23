"""Response shape for GET /history — one row per past chat request."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    timestamp: datetime
    prompt: str
    response: str

    routing_tier: str
    original_tier: str
    escalated: bool
    task_type: str
    reasoning_level: str
    confidence: float
    routing_reason: str

    classifier_model: str
    fallback_used: bool

    provider: str
    model: str
    input_tokens: int
    output_tokens: int

    classifier_cost: float
    model_cost: float
    total_cost: float
    total_latency_ms: float
