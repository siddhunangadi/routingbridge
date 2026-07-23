"""Output of the routing engine: which provider/model to call, and why."""

from pydantic import BaseModel

from backend.schemas.routing_decision import RoutingTier


class RoutingResult(BaseModel):
    provider: str
    model: str
    tier: RoutingTier
    original_tier: RoutingTier
    escalated: bool
    reasons: list[str]
