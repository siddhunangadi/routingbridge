"""The one table this app needs: a flat log of every chat request.

Deliberately denormalized (routing info, classifier info, and provider
info all live on one row) instead of split across related tables — there's
exactly one kind of event happening here, so one table models it exactly.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.db import Base


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    prompt: Mapped[str] = mapped_column(String, nullable=False)
    response: Mapped[str] = mapped_column(String, nullable=False)

    # routing decision
    routing_tier: Mapped[str] = mapped_column(String, nullable=False)
    original_tier: Mapped[str] = mapped_column(String, nullable=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    task_type: Mapped[str] = mapped_column(String)
    reasoning_level: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    routing_reason: Mapped[str] = mapped_column(String)

    # classifier metadata
    classifier_model: Mapped[str] = mapped_column(String)
    classifier_latency_ms: Mapped[float] = mapped_column(Float)
    classifier_cost: Mapped[float] = mapped_column(Float)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)

    # final model call
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    model_cost: Mapped[float] = mapped_column(Float)

    # totals
    total_cost: Mapped[float] = mapped_column(Float)
    total_latency_ms: Mapped[float] = mapped_column(Float)

    # quality verification (only run for BASIC/STANDARD — null means "not verified")
    quality_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    quality_reason: Mapped[str | None] = mapped_column(String, nullable=True)
