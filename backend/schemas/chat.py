"""Request/response contract for POST /chat."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    prompt: str
    response: str

    routing_tier: str
    original_tier: str
    escalated: bool
    task_type: str
    reasoning_level: str
    confidence: float
    routing_reason: list[str]

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

    quality_passed: bool | None
    quality_reason: str | None

    timestamp: datetime
