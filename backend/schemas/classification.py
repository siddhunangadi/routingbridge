"""Pydantic schemas for prompt complexity classification.

Two layers on purpose:
  - `ClassificationResult` is exactly the JSON we ask the LLM to return.
    Validating the raw LLM output against this schema is what turns an
    unstructured API response into something the routing engine can trust.
  - `ClassificationOutcome` wraps that result with the operational metadata
    (latency, cost, whether we had to fall back) that the analytics
    dashboard needs later. The LLM never sees or produces this outer layer.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Complexity(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"


class ClassificationResult(BaseModel):
    """The structured output we require from the classifier model."""

    complexity: Complexity
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=300)


class ClassificationOutcome(BaseModel):
    """Classification result plus the metadata needed for cost/latency analytics."""

    result: ClassificationResult
    classifier_model: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost: float
    fallback_used: bool
