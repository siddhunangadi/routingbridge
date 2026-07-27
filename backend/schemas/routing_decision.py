"""Pydantic schemas for the classifier's routing decision.

Named "routing decision" rather than "classification" deliberately: the
router model isn't measuring some objective property of the prompt, it's
making a judgment call about which tier should handle it. That framing
matches what the system actually does.

Two layers on purpose:
  - `RoutingDecision` is exactly the JSON we ask the LLM to return.
    Validating raw LLM output against this schema is what turns an
    unstructured API response into something the routing engine can trust.
  - `RoutingDecisionOutcome` wraps that decision with the operational
    metadata (latency, cost, whether we had to fall back) that the
    analytics dashboard needs later. The LLM never produces this outer layer.
"""

from enum import Enum

from pydantic import BaseModel, Field


class RoutingTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    ADVANCED = "ADVANCED"


class ReasoningLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class RoutingDecision(BaseModel):
    """The structured output we require from the classifier model.

    `task_type` and `reasoning_level` are informational context beyond the
    bare tier — they don't drive routing logic today, but they're exactly
    the kind of fields a later analytics view ("what task types dominate
    our ADVANCED tier?") would want, and they cost nothing extra to capture
    since the classifier is already making the judgment call.
    """

    routing_tier: RoutingTier
    task_type: str = Field(min_length=1, max_length=50)
    reasoning_level: ReasoningLevel
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=300)


class RoutingDecisionOutcome(BaseModel):
    """Routing decision plus the metadata needed for cost/latency analytics."""

    decision: RoutingDecision
    classifier_model: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost: float
    fallback_used: bool
