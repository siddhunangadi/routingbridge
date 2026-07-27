"""Query logic for GET /stats: aggregate numbers for the dashboard.

`estimated_savings` is the one non-trivial number here: for every request
that *didn't* use the ADVANCED-tier model, we recompute what it would have
cost at ADVANCED pricing (same token counts) and sum the difference. That's
the concrete answer to "how much is this routing actually saving us?" —
the whole point of the product.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database.models import ExecutionResult, QualityResult, RoutingDecision
from backend.schemas.stats import StatsResponse
from backend.services.cost_estimator import estimate_cost
from backend.utils.yaml_config import load_routing_config


def get_stats(db: Session) -> StatsResponse:
    total_requests = db.query(func.count(RoutingDecision.request_id)).scalar() or 0

    if total_requests == 0:
        return StatsResponse(
            total_requests=0,
            total_cost=0.0,
            avg_latency_ms=0.0,
            requests_per_tier={},
            cost_per_model={},
            estimated_savings=0.0,
            quality_verified_count=0,
            quality_pass_rate=None,
        )

    total_cost = db.query(func.sum(ExecutionResult.estimated_cost)).scalar() or 0.0
    avg_latency_ms = db.query(func.avg(ExecutionResult.latency_ms)).scalar() or 0.0

    requests_per_tier = dict(
        db.query(RoutingDecision.final_tier, func.count(RoutingDecision.request_id))
        .group_by(RoutingDecision.final_tier)
        .all()
    )
    cost_per_model = dict(
        db.query(RoutingDecision.selected_model, func.sum(ExecutionResult.estimated_cost))
        .join(ExecutionResult, ExecutionResult.request_id == RoutingDecision.request_id)
        .group_by(RoutingDecision.selected_model)
        .all()
    )

    advanced_model = load_routing_config()["tiers"]["advanced"]["model"]
    rows = (
        db.query(
            RoutingDecision.selected_model,
            ExecutionResult.input_tokens,
            ExecutionResult.output_tokens,
            ExecutionResult.estimated_cost,
        )
        .join(ExecutionResult, ExecutionResult.request_id == RoutingDecision.request_id)
        .all()
    )
    estimated_savings = sum(
        max(estimate_cost(advanced_model, input_tokens, output_tokens) - model_cost, 0.0)
        for model, input_tokens, output_tokens, model_cost in rows
        if model != advanced_model
    )

    quality_verified_count = db.query(func.count(QualityResult.request_id)).scalar() or 0
    quality_pass_rate = None
    if quality_verified_count > 0:
        passed_count = (
            db.query(func.count(QualityResult.request_id))
            .filter(QualityResult.verdict.is_(True))
            .scalar()
            or 0
        )
        quality_pass_rate = round(passed_count / quality_verified_count, 4)

    return StatsResponse(
        total_requests=total_requests,
        total_cost=round(total_cost, 6),
        avg_latency_ms=round(avg_latency_ms, 2),
        requests_per_tier=requests_per_tier,
        cost_per_model={k: round(v, 6) for k, v in cost_per_model.items()},
        estimated_savings=round(estimated_savings, 6),
        quality_verified_count=quality_verified_count,
        quality_pass_rate=quality_pass_rate,
    )
