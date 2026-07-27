"""Query logic for GET /history: join the four normalized tables back into
one row per request — the same shape RequestLog used to provide directly.
"""

from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.database.models import ExecutionResult, QualityResult, Request, RoutingDecision
from backend.schemas.history import HistoryItem


def get_history(db: Session, *, limit: int, offset: int) -> list[HistoryItem]:
    rows = (
        db.query(Request, RoutingDecision, ExecutionResult, QualityResult)
        .join(RoutingDecision, RoutingDecision.request_id == Request.request_id)
        .join(ExecutionResult, ExecutionResult.request_id == Request.request_id)
        .outerjoin(QualityResult, QualityResult.request_id == Request.request_id)
        .order_by(desc(Request.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        HistoryItem(
            id=req.request_id,
            timestamp=req.created_at,
            prompt=req.prompt,
            response=req.response,
            routing_tier=decision.final_tier,
            original_tier=decision.classifier_tier,
            escalated=decision.escalation_reason is not None,
            task_type=decision.task_type,
            reasoning_level="",
            confidence=decision.classifier_confidence,
            routing_reason=decision.routing_reasoning,
            classifier_model="",
            fallback_used=False,
            provider=decision.selected_provider,
            model=decision.selected_model,
            input_tokens=execution.input_tokens,
            output_tokens=execution.output_tokens,
            classifier_cost=0.0,
            model_cost=execution.estimated_cost,
            total_cost=execution.estimated_cost,
            total_latency_ms=execution.latency_ms,
            quality_passed=quality.verdict if quality else None,
            quality_reason=quality.verifier_reasoning if quality else None,
        )
        for req, decision, execution, quality in rows
    ]
