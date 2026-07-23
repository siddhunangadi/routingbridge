"""Pydantic schema for the quality-verification judge's output."""

from pydantic import BaseModel, Field


class QualityVerdict(BaseModel):
    """Structured output required from the quality-judge model."""

    passed: bool
    reason: str = Field(min_length=1, max_length=200)
