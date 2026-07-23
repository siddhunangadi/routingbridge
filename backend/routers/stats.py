"""GET /stats — aggregate analytics for the dashboard.

`estimated_savings` is the one non-trivial number here: for every request
that *didn't* use the ADVANCED-tier model, we recompute what it would have
cost at ADVANCED pricing (same token counts) and sum the difference. That's
the concrete answer to "how much is this routing actually saving us?" —
the whole point of the product.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import RequestLog
from backend.schemas.stats import StatsResponse
from backend.services.cost_estimator import estimate_cost
from backend.utils.yaml_config import load_routing_config

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    total_requests = db.query(func.count(RequestLog.id)).scalar() or 0

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

    total_cost = db.query(func.sum(RequestLog.total_cost)).scalar() or 0.0
    avg_latency_ms = db.query(func.avg(RequestLog.total_latency_ms)).scalar() or 0.0

    requests_per_tier = dict(
        db.query(RequestLog.routing_tier, func.count(RequestLog.id))
        .group_by(RequestLog.routing_tier)
        .all()
    )
    cost_per_model = dict(
        db.query(RequestLog.model, func.sum(RequestLog.total_cost))
        .group_by(RequestLog.model)
        .all()
    )

    advanced_model = load_routing_config()["tiers"]["advanced"]["model"]
    rows = db.query(
        RequestLog.model, RequestLog.input_tokens, RequestLog.output_tokens, RequestLog.model_cost
    ).all()
    estimated_savings = sum(
        max(estimate_cost(advanced_model, input_tokens, output_tokens) - model_cost, 0.0)
        for model, input_tokens, output_tokens, model_cost in rows
        if model != advanced_model
    )

    # quality_passed is NULL for ADVANCED-tier rows (never verified) — only
    # count rows where verification actually ran.
    quality_verified_count = (
        db.query(func.count(RequestLog.id))
        .filter(RequestLog.quality_passed.isnot(None))
        .scalar()
        or 0
    )
    quality_pass_rate = None
    if quality_verified_count > 0:
        passed_count = (
            db.query(func.count(RequestLog.id))
            .filter(RequestLog.quality_passed.is_(True))
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
