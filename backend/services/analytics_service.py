"""Read-side queries for GET /analytics/routing, /analytics/patterns, and
/analytics/recommendations. Pure aggregation over the tables PR1
persists — this module writes nothing; routing_learning.py owns writes.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database.models import (
    ExecutionResult,
    OptimizationRecommendation,
    QualityResult,
    Request,
    RoutingDecision,
    RoutingPattern,
)
from backend.schemas.analytics import (
    DailyMetric,
    ModelStats,
    ProviderStats,
    RecommendationResponse,
    RoutingOverviewResponse,
    RoutingPatternResponse,
    TaskTypeStats,
)
from backend.services.query_helpers import PASS_RATE


def _grouped_stats(db: Session, *group_cols):
    """One row per distinct value of group_cols, with request_count/average
    cost & latency/pass_rate — the same shape providers, models, and task
    types all need, just grouped by a different column set."""
    return (
        db.query(
            *group_cols,
            func.count(RoutingDecision.request_id).label("request_count"),
            func.avg(ExecutionResult.estimated_cost).label("average_cost"),
            func.avg(ExecutionResult.latency_ms).label("average_latency_ms"),
            PASS_RATE.label("pass_rate"),
        )
        .join(ExecutionResult, ExecutionResult.request_id == RoutingDecision.request_id)
        .outerjoin(QualityResult, QualityResult.request_id == RoutingDecision.request_id)
        .group_by(*group_cols)
        .all()
    )


def get_routing_overview(db: Session) -> RoutingOverviewResponse:
    providers = [
        ProviderStats(
            provider=row.selected_provider,
            request_count=row.request_count,
            average_cost=round(row.average_cost, 6),
            average_latency_ms=round(row.average_latency_ms, 2),
            pass_rate=round(row.pass_rate, 4) if row.pass_rate is not None else None,
        )
        for row in _grouped_stats(db, RoutingDecision.selected_provider)
    ]

    models = [
        ModelStats(
            provider=row.selected_provider,
            model=row.selected_model,
            request_count=row.request_count,
            average_cost=round(row.average_cost, 6),
            average_latency_ms=round(row.average_latency_ms, 2),
            pass_rate=round(row.pass_rate, 4) if row.pass_rate is not None else None,
        )
        for row in _grouped_stats(db, RoutingDecision.selected_provider, RoutingDecision.selected_model)
    ]

    task_types = [
        TaskTypeStats(
            task_type=row.task_type,
            request_count=row.request_count,
            average_cost=round(row.average_cost, 6),
            average_latency_ms=round(row.average_latency_ms, 2),
            pass_rate=round(row.pass_rate, 4) if row.pass_rate is not None else None,
        )
        for row in _grouped_stats(db, RoutingDecision.task_type)
    ]

    tier_distribution = dict(
        db.query(RoutingDecision.final_tier, func.count(RoutingDecision.request_id))
        .group_by(RoutingDecision.final_tier)
        .all()
    )

    daily_rows = (
        db.query(
            func.date(Request.created_at),
            func.count(Request.request_id),
            func.sum(ExecutionResult.estimated_cost),
            func.avg(ExecutionResult.latency_ms),
        )
        .join(ExecutionResult, ExecutionResult.request_id == Request.request_id)
        .group_by(func.date(Request.created_at))
        .order_by(func.date(Request.created_at))
        .all()
    )
    daily_metrics = [
        DailyMetric(
            day=day,
            request_count=count,
            total_cost=round(total_cost or 0.0, 6),
            average_latency_ms=round(average_latency or 0.0, 2),
        )
        for day, count, total_cost, average_latency in daily_rows
    ]

    return RoutingOverviewResponse(
        providers=providers,
        models=models,
        task_types=task_types,
        tier_distribution=tier_distribution,
        daily_metrics=daily_metrics,
    )


def get_patterns(db: Session) -> list[RoutingPatternResponse]:
    patterns = db.query(RoutingPattern).order_by(RoutingPattern.sample_size.desc()).all()
    return [RoutingPatternResponse.model_validate(p) for p in patterns]


def get_recommendations(db: Session) -> list[RecommendationResponse]:
    recommendations = (
        db.query(OptimizationRecommendation)
        .order_by(OptimizationRecommendation.created_at.desc())
        .all()
    )
    return [RecommendationResponse.model_validate(r) for r in recommendations]
