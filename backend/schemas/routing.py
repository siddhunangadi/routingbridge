"""Output of the routing engine: which provider/model to call, and why."""

from pydantic import BaseModel, Field

from backend.schemas.routing_decision import RoutingTier


class RoutingCandidate(BaseModel):
    provider: str
    model: str
    max_output_tokens: int


class RoutingResult(BaseModel):
    provider: str
    model: str
    max_output_tokens: int
    tier: RoutingTier
    original_tier: RoutingTier
    escalated: bool
    reasons: list[str]
    candidates: list[RoutingCandidate] = Field(default_factory=list)
