"""Transactional persistence AND read-side reconstruction for one routing
decision.

`record()` is the single place that writes the four normalized tables
(requests, routing_decisions, execution_results, quality_results) for a
request. All four inserts go into one SQLAlchemy transaction — no
BackgroundTasks, no fire-and-forget logging. If the commit fails, the
exception propagates to the router: audit integrity is a correctness
requirement, not a best-effort side effect.

Both are plain module functions, not a class — there's no instance state
here (every call is a fresh, independent DB operation), matching
routing_learning.refresh() and routing_agent.investigate() elsewhere in
this codebase.

DecisionCard is NOT persisted as a JSON blob alongside the relational
columns — that would duplicate the same facts twice with no independent
value. `routing_decisions`'s columns (joined with `requests` for the
timestamp and `execution_results` for cost/latency) are the single
source of truth; `get_decision_card()` builds a DecisionCard from those
rows on demand, plus an `optimization_recommendations` lookup for PR3's
recommendation surface. See docs/pr3-decision-intelligence.md.

`record_failure()` is the counterpart for the unhappy path: see
docs/architecture.md's "Failure handling" section for what calls it and
why the audit trail covers failures, not just successes.
"""

import hashlib
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from backend.database.models import (
    ExecutionResult,
    FailedRequest,
    OptimizationRecommendation,
    QualityResult,
    Request,
    RoutingDecision,
)

logger = logging.getLogger(__name__)
from backend.schemas.decision_card import DecisionCard, DecisionReason, RecommendationSummary
from backend.schemas.quality import QualityVerdict
from backend.schemas.routing import RoutingResult
from backend.schemas.routing_decision import RoutingDecisionOutcome
from backend.utils.yaml_config import load_routing_config


def _normalize_prompt(prompt: str) -> str:
    return " ".join(prompt.lower().split())


def _prompt_hash(normalized_prompt: str) -> str:
    return hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest()


def record(
    db: Session,
    *,
    request_id: str,
    prompt: str,
    response: str,
    created_at: datetime,
    decision_outcome: RoutingDecisionOutcome,
    routing_result: RoutingResult,
    total_latency_ms: float,
    input_tokens: int,
    output_tokens: int,
    total_cost: float,
    provider_success: bool,
    error_message: str | None,
    quality_verdict: QualityVerdict | None,
) -> None:
    decision = decision_outcome.decision
    normalized_prompt = _normalize_prompt(prompt)
    policy_version = load_routing_config().get("policy_version", "v1.0")

    escalation_reason = None
    if routing_result.escalated:
        escalation_reason = routing_result.reasons[-1]

    db.add(
        Request(
            request_id=request_id,
            prompt=prompt,
            response=response,
            normalized_prompt=normalized_prompt,
            prompt_hash=_prompt_hash(normalized_prompt),
            created_at=created_at,
        )
    )
    # requests has no ORM relationship() to the other three tables (only
    # column-level ForeignKeys), so the unit of work has no dependency
    # graph to order inserts by — an explicit flush is what guarantees
    # this row exists before the FK-referencing inserts below run.
    # SQLite silently tolerated the unordered case (no FK enforcement by
    # default); Postgres/Supabase does not — this surfaced as a real
    # ForeignKeyViolation during the Supabase migration.
    db.flush()
    db.add(
        RoutingDecision(
            request_id=request_id,
            classifier_tier=decision.routing_tier.value,
            final_tier=routing_result.tier.value,
            classifier_confidence=decision.confidence,
            task_type=decision.task_type,
            task_subcategory=None,
            classifier_reasoning=decision.reason,
            routing_reasoning=" | ".join(routing_result.reasons),
            selected_provider=routing_result.provider,
            selected_model=routing_result.model,
            routing_policy_version=policy_version,
            escalation_reason=escalation_reason,
        )
    )
    db.add(
        ExecutionResult(
            request_id=request_id,
            provider_success=provider_success,
            latency_ms=total_latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=total_cost,
            error_message=error_message,
        )
    )
    if quality_verdict is not None:
        db.add(
            QualityResult(
                request_id=request_id,
                verdict=quality_verdict.passed,
                quality_score=None,
                verifier_reasoning=quality_verdict.reason,
                verified_at=created_at,
            )
        )

    db.commit()


def record_failure(
    db: Session,
    *,
    request_id: str,
    prompt: str,
    stage: str,
    provider: str | None,
    model: str | None,
    error_message: str,
    created_at: datetime,
) -> None:
    """Persist a failure audit record for a request that never reached
    `record()` — a provider exception, a cost-estimation error (e.g. a
    model missing from pricing.yaml), or a persistence failure in
    `record()` itself.

    Must never raise: this is called from exception handlers, and a
    broken audit write must not mask the original failure or crash the
    error response the caller is trying to return. If the insert itself
    fails, it's rolled back and logged at CRITICAL — that's the one gap
    the audit trail can have, and it's visible in logs, not silent.
    """
    try:
        db.rollback()
        db.add(
            FailedRequest(
                request_id=request_id,
                prompt=prompt,
                stage=stage,
                provider=provider,
                model=model,
                error_message=error_message[:2000],
                status="failed",
                created_at=created_at,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.critical(
            "Failed to persist failure audit record for request_id=%s (stage=%s)",
            request_id,
            stage,
            exc_info=True,
        )


def _build_reasoning_steps(decision: RoutingDecision) -> list[DecisionReason]:
    """Deterministic, derived entirely from the persisted row — no LLM
    involved. Mirrors the actual sequence routing_engine.py/chat.py ran:
    classify -> (maybe escalate) -> map tier to provider/model -> done.
    """
    steps = [
        DecisionReason(step=1, description=f"Task classified as {decision.task_type}"),
        DecisionReason(
            step=2,
            description=(
                f"Classifier confidence = {decision.classifier_confidence:.2f}, "
                f"initial tier = {decision.classifier_tier}"
            ),
        ),
    ]
    if decision.escalation_reason:
        steps.append(
            DecisionReason(
                step=3,
                description=f"Escalated to {decision.final_tier} tier — {decision.escalation_reason}",
            )
        )
    else:
        steps.append(
            DecisionReason(step=3, description=f"Selected {decision.final_tier} tier")
        )
    steps.append(
        DecisionReason(
            step=len(steps) + 1,
            description=(
                f"{decision.final_tier} tier maps to {decision.selected_provider}/"
                f"{decision.selected_model} under policy {decision.routing_policy_version}"
            ),
        )
    )
    steps.append(DecisionReason(step=len(steps) + 1, description="Final routing complete"))
    return steps


def _find_matching_recommendation(
    db: Session, decision: RoutingDecision
) -> OptimizationRecommendation | None:
    """A recommendation applies to a decision only if all of policy_version,
    task_type, task_subcategory, and the currently-selected provider/model
    match exactly — the same attribution routing_learning.py uses to keep
    recommendations from one policy epoch out of another (docs/pr2-analytics.md).
    """
    return (
        db.query(OptimizationRecommendation)
        .filter(
            OptimizationRecommendation.policy_version == decision.routing_policy_version,
            OptimizationRecommendation.task_type == decision.task_type,
            OptimizationRecommendation.task_subcategory == decision.task_subcategory,
            OptimizationRecommendation.current_provider == decision.selected_provider,
            OptimizationRecommendation.current_model == decision.selected_model,
        )
        .first()
    )


def _to_recommendation_summary(rec: OptimizationRecommendation) -> RecommendationSummary:
    return RecommendationSummary(
        recommendation_id=rec.recommendation_id,
        recommended_provider=rec.recommended_provider,
        recommended_model=rec.recommended_model,
        expected_cost_change=rec.expected_cost_change,
        expected_quality_change=rec.expected_quality_change,
        confidence=rec.confidence,
        summary=rec.reason,
    )


def get_decision_card(db: Session, request_id: str) -> tuple[DecisionCard, RecommendationSummary | None] | None:
    """Build the DecisionCard for a past request, plus its matching
    recommendation if one exists. Returns None if request_id is unknown.

    Entirely a read: joins requests + routing_decisions + execution_results
    (all written once, transactionally, by `record()`) and looks up
    optimization_recommendations. Never writes anything, never touches
    routing.yaml, never changes what was actually routed.
    """
    row = (
        db.query(Request, RoutingDecision, ExecutionResult)
        .join(RoutingDecision, RoutingDecision.request_id == Request.request_id)
        .join(ExecutionResult, ExecutionResult.request_id == Request.request_id)
        .filter(Request.request_id == request_id)
        .first()
    )
    if row is None:
        return None
    request, decision, execution = row

    recommendation = _find_matching_recommendation(db, decision)

    card = DecisionCard(
        request_id=request.request_id,
        timestamp=request.created_at,
        policy_version=decision.routing_policy_version,
        task_type=decision.task_type,
        task_subcategory=decision.task_subcategory,
        selected_provider=decision.selected_provider,
        selected_model=decision.selected_model,
        selected_tier=decision.final_tier,
        routing_reason=decision.routing_reasoning.split(" | "),
        estimated_cost=execution.estimated_cost,
        estimated_latency_ms=execution.latency_ms,
        confidence=decision.classifier_confidence,
        reasoning_steps=_build_reasoning_steps(decision),
        recommendation_available=recommendation is not None,
        recommendation_id=recommendation.recommendation_id if recommendation else None,
    )

    summary = _to_recommendation_summary(recommendation) if recommendation else None
    return card, summary
