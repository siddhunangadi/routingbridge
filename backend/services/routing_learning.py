"""routing_learning.refresh(): recompute routing_patterns and generate
optimization_recommendations from historical decisions.

Runs only when POST /analytics/refresh is called explicitly — never on
the live request path and never on a schedule. It reads
routing_decisions + execution_results + quality_results, groups by
(task_type, task_subcategory, provider, model, tier), and rewrites
routing_patterns wholesale (delete + reinsert — patterns have no
identity worth preserving across refreshes, they're a snapshot). This is
an O(n) full-table scan of routing_decisions on every refresh; fine at
this project's scale, but if routing_decisions grows into the hundreds
of thousands of rows, revisit this as an incremental upsert keyed by
(task_type, task_subcategory, provider, model, tier, policy_version) that
updates a running average instead of recomputing from scratch. See
docs/pr2-analytics.md for the full trade-off writeup.

Recommendations are advisory only. This module NEVER writes to
routing.yaml and the routing engine never reads optimization_recommendations
— a human reviews GET /analytics/recommendations and decides whether to
bump routing.yaml's policy_version. See docs/pr2-analytics.md.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database.models import (
    ExecutionResult,
    OptimizationRecommendation,
    QualityResult,
    RoutingDecision,
    RoutingPattern,
)
from backend.schemas.analytics import RefreshResult
from backend.services.query_helpers import PASS_RATE
from backend.utils.yaml_config import load_routing_config


def refresh(db: Session) -> RefreshResult:
    rows = (
        db.query(
            RoutingDecision.task_type,
            RoutingDecision.task_subcategory,
            RoutingDecision.selected_provider,
            RoutingDecision.selected_model,
            RoutingDecision.final_tier,
            RoutingDecision.routing_policy_version,
            func.count(RoutingDecision.request_id).label("sample_size"),
            func.avg(ExecutionResult.estimated_cost).label("average_cost"),
            func.avg(ExecutionResult.latency_ms).label("average_latency"),
            PASS_RATE.label("pass_rate"),
        )
        .join(ExecutionResult, ExecutionResult.request_id == RoutingDecision.request_id)
        .outerjoin(QualityResult, QualityResult.request_id == RoutingDecision.request_id)
        .group_by(
            RoutingDecision.task_type,
            RoutingDecision.task_subcategory,
            RoutingDecision.selected_provider,
            RoutingDecision.selected_model,
            RoutingDecision.final_tier,
            RoutingDecision.routing_policy_version,
        )
        .all()
    )

    db.query(RoutingPattern).delete()
    patterns = [
        RoutingPattern(
            task_type=row.task_type,
            task_subcategory=row.task_subcategory,
            provider=row.selected_provider,
            model=row.selected_model,
            tier=row.final_tier,
            policy_version=row.routing_policy_version,
            sample_size=row.sample_size,
            average_cost=row.average_cost,
            average_latency=row.average_latency,
            pass_rate=row.pass_rate,
            failure_rate=(1.0 - row.pass_rate) if row.pass_rate is not None else None,
        )
        for row in rows
    ]
    db.add_all(patterns)

    recommendations = _generate_recommendations(patterns)
    db.query(OptimizationRecommendation).delete()
    db.add_all(recommendations)

    db.commit()
    return RefreshResult(
        patterns_updated=len(patterns), recommendations_generated=len(recommendations)
    )


def _generate_recommendations(patterns: list[RoutingPattern]) -> list[OptimizationRecommendation]:
    """For each tier, compare its routing.yaml-configured model against the
    best-performing alternative pattern seen for the same task_type at that
    tier, under the SAME policy_version. A recommendation only gets
    generated when the alternative both has enough samples to trust
    (min_sample_size) and a meaningfully better pass_rate than the
    configured model currently achieves.

    Restricting to the current policy_version matters: routing_patterns
    from a since-superseded policy can carry a stale sample_size/pass_rate
    for what "the configured model" even was, so comparing across policy
    epochs would produce a recommendation the current policy never earned.
    """
    config = load_routing_config()
    min_sample_size = config["learning"]["min_sample_size"]
    tiers_cfg = config["tiers"]
    current_policy_version = config.get("policy_version", "v1.0")

    by_task_and_tier: dict[tuple[str, str], list[RoutingPattern]] = {}
    for pattern in patterns:
        if pattern.policy_version != current_policy_version:
            continue
        by_task_and_tier.setdefault((pattern.task_type, pattern.tier), []).append(pattern)

    recommendations = []
    for (task_type, tier), group in by_task_and_tier.items():
        tier_cfg = tiers_cfg.get(tier.lower())
        if tier_cfg is None:
            continue

        current_provider, current_model = tier_cfg["provider"], tier_cfg["model"]
        current = next(
            (p for p in group if p.provider == current_provider and p.model == current_model),
            None,
        )
        if current is None or current.pass_rate is None:
            continue

        candidates = [
            p
            for p in group
            if (p.provider, p.model) != (current_provider, current_model)
            and p.sample_size >= min_sample_size
            and p.pass_rate is not None
            and p.pass_rate > current.pass_rate
        ]
        if not candidates:
            continue

        best = max(candidates, key=lambda p: p.pass_rate)
        recommendations.append(
            _build_recommendation(task_type, current_policy_version, current, best)
        )

    return recommendations


def _build_recommendation(
    task_type: str,
    policy_version: str,
    current: RoutingPattern,
    best: RoutingPattern,
) -> OptimizationRecommendation:
    """Assemble one OptimizationRecommendation from the current tier's
    configured pattern and the best-performing alternative found for it."""
    return OptimizationRecommendation(
        task_type=task_type,
        task_subcategory=current.task_subcategory,
        policy_version=policy_version,
        current_provider=current.provider,
        recommended_provider=best.provider,
        current_model=current.model,
        recommended_model=best.model,
        expected_cost_change=round(best.average_cost - current.average_cost, 6),
        expected_quality_change=round(best.pass_rate - current.pass_rate, 4),
        confidence=round(best.pass_rate, 4),
        reason=(
            f"{task_type} prompts on {current.model} pass {current.pass_rate:.0%} "
            f"of quality checks (n={current.sample_size}); {best.model} achieves "
            f"{best.pass_rate:.0%} (n={best.sample_size}) at the same tier."
        ),
        evidence={
            "current": {
                "provider": current.provider,
                "model": current.model,
                "sample_size": current.sample_size,
                "average_cost": current.average_cost,
                "pass_rate": current.pass_rate,
            },
            "recommended": {
                "provider": best.provider,
                "model": best.model,
                "sample_size": best.sample_size,
                "average_cost": best.average_cost,
                "pass_rate": best.pass_rate,
            },
        },
        status="pending",
    )
