"""Normalized schema for routing decision intelligence.

Replaces the single flat `RequestLog` table with four tables, one per
stage of the request lifecycle (request -> routing decision -> execution
result -> quality result), all keyed by `request_id`. This is what makes
historical analytics (PR2) and policy simulation (PR3) possible without
scanning a denormalized blob: each stage's data lives where a query about
just that stage expects it.

`RoutingPolicy` is the seed of a versioned policy registry: routing.yaml's
current tier config gets snapshotted here under a version tag, so every
routing_decision row can point at exactly the policy that produced it.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.db import Base


class Request(Base):
    __tablename__ = "requests"

    request_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    prompt: Mapped[str] = mapped_column(String, nullable=False)
    response: Mapped[str] = mapped_column(String, nullable=False)
    normalized_prompt: Mapped[str] = mapped_column(String, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class RoutingDecision(Base):
    __tablename__ = "routing_decisions"

    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("requests.request_id"), primary_key=True
    )

    classifier_tier: Mapped[str] = mapped_column(String, nullable=False)
    final_tier: Mapped[str] = mapped_column(String, nullable=False)
    classifier_confidence: Mapped[float] = mapped_column(Float)
    calibrated_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classifier_source: Mapped[str] = mapped_column(String, nullable=False, default="llm_fallback")
    classifier_model: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    p_basic: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_standard: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_advanced: Mapped[float | None] = mapped_column(Float, nullable=True)
    classifier_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    classifier_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    task_type: Mapped[str] = mapped_column(String)
    task_subcategory: Mapped[str | None] = mapped_column(String, nullable=True)
    classifier_reasoning: Mapped[str] = mapped_column(String)
    routing_reasoning: Mapped[str] = mapped_column(String)
    selected_provider: Mapped[str] = mapped_column(String, nullable=False)
    selected_model: Mapped[str] = mapped_column(String, nullable=False)
    routing_policy_version: Mapped[str] = mapped_column(String, nullable=False)
    escalation_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class ExecutionResult(Base):
    __tablename__ = "execution_results"

    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("requests.request_id"), primary_key=True
    )

    provider_success: Mapped[bool] = mapped_column(Boolean, default=True)
    latency_ms: Mapped[float] = mapped_column(Float)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    estimated_cost: Mapped[float] = mapped_column(Float)
    generation_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    generation_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)


class QualityResult(Base):
    __tablename__ = "quality_results"

    request_id: Mapped[str] = mapped_column(
        String, ForeignKey("requests.request_id"), primary_key=True
    )

    verdict: Mapped[bool] = mapped_column(Boolean, nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verifier_reasoning: Mapped[str] = mapped_column(String)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class FailedRequest(Base):
    """One row per request that never produced a routing_decisions /
    execution_results row — a provider failure, a cost-estimation error, a
    persistence error, or any other unexpected exception in the /chat
    pipeline. `requests`/`routing_decisions`/etc. only ever describe
    successful requests (their columns are NOT NULL on data only a success
    produces), so a failure can't be recorded there without weakening that
    guarantee. This table exists so a failure is never simply dropped from
    the audit trail — see decision_service.record_failure()."""

    __tablename__ = "failed_requests"

    request_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    prompt: Mapped[str] = mapped_column(String, nullable=False)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="failed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class RoutingPolicy(Base):
    __tablename__ = "routing_policies"

    version: Mapped[str] = mapped_column(String, primary_key=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class RoutingPattern(Base):
    """One aggregated row per (task_type, task_subcategory, provider, model,
    tier) combination ever seen — recomputed wholesale by
    routing_learning.refresh(), never written by the live request path."""

    __tablename__ = "routing_patterns"
    __table_args__ = (
        UniqueConstraint(
            "task_type", "task_subcategory", "provider", "model", "tier", "policy_version",
            name="uq_routing_pattern_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    task_subcategory: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    # Which routing.yaml policy_version was active for the requests this
    # row summarizes. Without this, a pattern silently blends requests
    # from different policies if routing.yaml changes between refreshes —
    # see docs/pr2-analytics.md.
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    average_cost: Mapped[float] = mapped_column(Float, nullable=False)
    average_latency: Mapped[float] = mapped_column(Float, nullable=False)
    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class OptimizationRecommendation(Base):
    """A recommendation routing_learning.py generated by comparing a tier's
    configured provider/model against a higher-performing alternative seen
    in routing_patterns. Advisory only — see routing.yaml's `learning`
    block and docs/pr2-analytics.md: nothing here is ever applied to live
    routing automatically."""

    __tablename__ = "optimization_recommendations"

    recommendation_id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    task_subcategory: Mapped[str | None] = mapped_column(String, nullable=True)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    current_provider: Mapped[str] = mapped_column(String, nullable=False)
    recommended_provider: Mapped[str] = mapped_column(String, nullable=False)
    current_model: Mapped[str] = mapped_column(String, nullable=False)
    recommended_model: Mapped[str] = mapped_column(String, nullable=False)
    expected_cost_change: Mapped[float] = mapped_column(Float, nullable=False)
    expected_quality_change: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    # The raw numbers `reason`'s prose summarizes, structured for a
    # dashboard or the future agent to quote directly instead of
    # re-deriving or re-parsing the sentence.
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class InvestigationReport(Base):
    """One run of the Routing Optimization Agent (PR4). Scalar columns are
    what a listing/filter would query by; `findings`/`suggested_actions`/
    `investigation_steps`/`tools_used` are JSON — same precedent as
    RoutingPolicy.config and OptimizationRecommendation.evidence. This
    table stores the agent's OWN output only: no routing_decisions,
    execution_results, or routing_patterns rows are duplicated here, only
    references to them (a recommendation_id, a task_type) inside the
    JSON findings — see docs/pr4-routing-agent.md."""

    __tablename__ = "investigation_reports"

    report_id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    executive_summary: Mapped[str] = mapped_column(String, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    findings: Mapped[list] = mapped_column(JSON, nullable=False)
    suggested_actions: Mapped[list] = mapped_column(JSON, nullable=False)
    investigation_steps: Mapped[list] = mapped_column(JSON, nullable=False)
    tools_used: Mapped[list] = mapped_column(JSON, nullable=False)
