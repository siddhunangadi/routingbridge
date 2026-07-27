"""The Routing Optimization Agent: a deterministic, offline pipeline that
investigates historical routing behavior and produces an InvestigationReport.

No LLM call happens anywhere in this module. "Agentic" here means a fixed
sequence of inspectable steps over PR1-PR3's data (routing_decisions,
execution_results, quality_results, routing_patterns,
optimization_recommendations) — not an LLM reasoning loop. That's a
deliberate choice, not a placeholder for one: see
docs/pr4-routing-agent.md for why an LLM would add cost, latency, and a
chain-of-thought-exposure risk for a job five SQL queries already do
exactly and reproducibly.

`investigate()` only ever writes to investigation_reports. It never
touches routing.yaml, routing_decisions, routing_patterns, or
optimization_recommendations — see the safety rules in
docs/pr4-routing-agent.md.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database.models import (
    ExecutionResult,
    InvestigationReport as InvestigationReportModel,
    OptimizationRecommendation,
    QualityResult,
    Request,
    RoutingDecision,
    RoutingPattern,
)
from backend.schemas.investigation import Evidence, Finding, InvestigationReport, SuggestedAction
from backend.services.query_helpers import PASS_RATE
from backend.utils.yaml_config import load_routing_config

DEGRADED_PASS_RATE_THRESHOLD = 0.7
COST_ANOMALY_MULTIPLIER = 1.5

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def investigate(db: Session) -> InvestigationReport:
    """Run the full investigation pipeline and persist the resulting report."""
    steps: list[str] = []
    tools: list[str] = []
    findings: list[Finding] = []

    config = load_routing_config()
    policy_version = config.get("policy_version", "v1.0")
    min_sample_size = config["learning"]["min_sample_size"]

    steps.append(f"Loaded active policy_version '{policy_version}' from routing.yaml")
    tools.append("utils.yaml_config.load_routing_config")

    patterns = db.query(RoutingPattern).filter(RoutingPattern.policy_version == policy_version).all()
    steps.append(f"Loaded {len(patterns)} routing_patterns row(s) for policy_version '{policy_version}'")
    tools.append("database.query(routing_patterns)")

    findings.extend(_find_degraded_task_types(patterns, min_sample_size, steps, tools))
    findings.extend(_find_expensive_task_type(patterns, steps, tools))
    findings.extend(_detect_cost_anomaly(db, steps, tools))
    findings.extend(_compare_policy_versions(db, policy_version, steps, tools))
    findings.extend(_validate_recommendations(db, policy_version, min_sample_size, steps, tools))

    steps.append(f"Assembled {len(findings)} finding(s) into the investigation report")

    suggested_actions = _build_suggested_actions(findings)
    steps.append(f"Derived {len(suggested_actions)} suggested action(s) from findings")

    overall_risk = _overall_risk(findings)
    overall_confidence = _overall_confidence(findings)
    executive_summary = _build_executive_summary(findings, overall_risk)

    report = InvestigationReport(
        report_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        policy_version=policy_version,
        executive_summary=executive_summary,
        findings=findings,
        suggested_actions=suggested_actions,
        risk_level=overall_risk,
        confidence=overall_confidence,
        investigation_steps=steps,
        tools_used=sorted(set(tools)),
    )

    db.add(
        InvestigationReportModel(
            report_id=report.report_id,
            created_at=report.created_at,
            policy_version=report.policy_version,
            executive_summary=report.executive_summary,
            risk_level=report.risk_level,
            confidence=report.confidence,
            findings=[f.model_dump() for f in report.findings],
            suggested_actions=[a.model_dump() for a in report.suggested_actions],
            investigation_steps=report.investigation_steps,
            tools_used=report.tools_used,
        )
    )
    db.commit()

    return report


def _find_degraded_task_types(
    patterns: list[RoutingPattern], min_sample_size: int, steps: list[str], tools: list[str]
) -> list[Finding]:
    steps.append(
        f"Scanned patterns for pass_rate below {DEGRADED_PASS_RATE_THRESHOLD:.0%} "
        f"with at least {min_sample_size} samples"
    )
    findings = []
    for pattern in patterns:
        if (
            pattern.pass_rate is not None
            and pattern.sample_size >= min_sample_size
            and pattern.pass_rate < DEGRADED_PASS_RATE_THRESHOLD
        ):
            findings.append(
                Finding(
                    finding_id=str(uuid.uuid4()),
                    category="model_degradation",
                    summary=(
                        f"{pattern.task_type} on {pattern.provider}/{pattern.model} "
                        f"({pattern.tier}) has a pass rate of {pattern.pass_rate:.0%}, "
                        f"below the {DEGRADED_PASS_RATE_THRESHOLD:.0%} threshold."
                    ),
                    risk_level="high",
                    confidence=round(1.0 - pattern.pass_rate, 4),
                    evidence=[
                        Evidence(
                            reference_type="routing_pattern",
                            reference_id=None,
                            description=f"{pattern.task_type}/{pattern.provider}/{pattern.model}",
                            metrics={
                                "sample_size": pattern.sample_size,
                                "pass_rate": pattern.pass_rate,
                                "average_cost": pattern.average_cost,
                            },
                        )
                    ],
                )
            )
    return findings


def _find_expensive_task_type(
    patterns: list[RoutingPattern], steps: list[str], tools: list[str]
) -> list[Finding]:
    if not patterns:
        return []
    steps.append("Ranked task types by average_cost to identify the most expensive")
    most_expensive = max(patterns, key=lambda p: p.average_cost)
    if len(patterns) < 2:
        return []
    others_avg = sum(p.average_cost for p in patterns if p is not most_expensive) / (len(patterns) - 1)
    if others_avg <= 0 or most_expensive.average_cost < others_avg * COST_ANOMALY_MULTIPLIER:
        return []
    return [
        Finding(
            finding_id=str(uuid.uuid4()),
            category="task_type_cost",
            summary=(
                f"{most_expensive.task_type} on {most_expensive.provider}/{most_expensive.model} "
                f"costs {most_expensive.average_cost / others_avg:.1f}x the average of other "
                f"task types."
            ),
            risk_level="medium",
            confidence=0.7,
            evidence=[
                Evidence(
                    reference_type="routing_pattern",
                    reference_id=None,
                    description=f"{most_expensive.task_type}/{most_expensive.provider}/{most_expensive.model}",
                    metrics={
                        "average_cost": most_expensive.average_cost,
                        "other_task_types_average_cost": round(others_avg, 6),
                        "sample_size": most_expensive.sample_size,
                    },
                )
            ],
        )
    ]


def _detect_cost_anomaly(db: Session, steps: list[str], tools: list[str]) -> list[Finding]:
    daily_rows = (
        db.query(
            func.date(Request.created_at),
            func.count(Request.request_id),
            func.sum(ExecutionResult.estimated_cost),
        )
        .join(ExecutionResult, ExecutionResult.request_id == Request.request_id)
        .group_by(func.date(Request.created_at))
        .order_by(func.date(Request.created_at))
        .all()
    )
    tools.append("database.query(requests JOIN execution_results, grouped by day)")
    steps.append(f"Computed daily cost-per-request trend across {len(daily_rows)} day(s) of history")

    if len(daily_rows) < 2:
        steps.append("Insufficient day-over-day history to evaluate a cost trend (need at least 2 days)")
        return []

    per_request = [(day, total_cost / count) for day, count, total_cost in daily_rows if count]
    *prior, latest = per_request
    prior_avg = sum(cost for _, cost in prior) / len(prior)
    latest_day, latest_cost = latest

    if prior_avg <= 0 or latest_cost < prior_avg * COST_ANOMALY_MULTIPLIER:
        return []

    return [
        Finding(
            finding_id=str(uuid.uuid4()),
            category="cost_trend",
            summary=(
                f"Cost per request on {latest_day} was {latest_cost / prior_avg:.1f}x the prior "
                f"{len(prior)}-day average."
            ),
            risk_level="medium",
            confidence=0.6,
            evidence=[
                Evidence(
                    reference_type="daily_metric",
                    reference_id=str(latest_day),
                    description="Cost-per-request, latest day vs. prior days",
                    metrics={
                        "latest_day_cost_per_request": round(latest_cost, 6),
                        "prior_days_average_cost_per_request": round(prior_avg, 6),
                    },
                )
            ],
        )
    ]


def _compare_policy_versions(
    db: Session, current_policy_version: str, steps: list[str], tools: list[str]
) -> list[Finding]:
    versions = [v for (v,) in db.query(RoutingPattern.policy_version).distinct().all()]
    tools.append("database.query(routing_patterns, distinct policy_version)")
    steps.append(f"Found {len(versions)} distinct policy_version(s) with routing_pattern data")

    if len(versions) < 2:
        steps.append("Only one policy_version observed — skipping policy comparison")
        return []

    def _weighted_stats(version: str) -> tuple[float, float, int]:
        rows = db.query(RoutingPattern).filter(RoutingPattern.policy_version == version).all()
        total_samples = sum(p.sample_size for p in rows) or 1
        avg_cost = sum(p.average_cost * p.sample_size for p in rows) / total_samples
        verified = [p for p in rows if p.pass_rate is not None]
        verified_samples = sum(p.sample_size for p in verified) or 1
        avg_pass_rate = (
            sum(p.pass_rate * p.sample_size for p in verified) / verified_samples if verified else None
        )
        return avg_cost, avg_pass_rate, total_samples

    other_versions = [v for v in versions if v != current_policy_version]
    findings = []
    current_cost, current_pass_rate, current_n = _weighted_stats(current_policy_version)
    for other in other_versions:
        other_cost, other_pass_rate, other_n = _weighted_stats(other)
        findings.append(
            Finding(
                finding_id=str(uuid.uuid4()),
                category="policy_comparison",
                summary=(
                    f"Policy {current_policy_version} averages ${current_cost:.6f}/request "
                    f"(n={current_n}) vs. policy {other} at ${other_cost:.6f}/request (n={other_n})."
                ),
                risk_level="low",
                confidence=0.5,
                evidence=[
                    Evidence(
                        reference_type="policy_version",
                        reference_id=current_policy_version,
                        description="Weighted average cost/pass-rate per policy_version",
                        metrics={
                            "current_average_cost": round(current_cost, 6),
                            "current_pass_rate": current_pass_rate,
                            "compared_policy_version": other,
                            "compared_average_cost": round(other_cost, 6),
                            "compared_pass_rate": other_pass_rate,
                        },
                    )
                ],
            )
        )
    return findings


def _validate_recommendations(
    db: Session, policy_version: str, min_sample_size: int, steps: list[str], tools: list[str]
) -> list[Finding]:
    recommendations = (
        db.query(OptimizationRecommendation)
        .filter(
            OptimizationRecommendation.policy_version == policy_version,
            OptimizationRecommendation.status == "pending",
        )
        .all()
    )
    tools.append("database.query(optimization_recommendations, status=pending)")
    steps.append(f"Re-validating {len(recommendations)} pending recommendation(s) against live data")

    findings = []
    for rec in recommendations:
        current_stats = _live_stats(db, policy_version, rec.task_type, rec.task_subcategory, rec.current_provider, rec.current_model)
        recommended_stats = _live_stats(db, policy_version, rec.task_type, rec.task_subcategory, rec.recommended_provider, rec.recommended_model)

        still_holds = (
            current_stats is not None
            and recommended_stats is not None
            and recommended_stats[2] is not None
            and current_stats[2] is not None
            and recommended_stats[0] >= min_sample_size
            and recommended_stats[2] > current_stats[2]
        )
        trustworthy = "trustworthy" if still_holds else "should be re-reviewed (no longer supported by live data)"
        findings.append(
            Finding(
                finding_id=str(uuid.uuid4()),
                category="recommendation_validation",
                summary=(
                    f"Recommendation {rec.recommendation_id} ({rec.task_type}: "
                    f"{rec.current_model} -> {rec.recommended_model}) is {trustworthy}."
                ),
                risk_level="low" if still_holds else "medium",
                confidence=recommended_stats[2] if still_holds and recommended_stats else 0.3,
                evidence=[
                    Evidence(
                        reference_type="optimization_recommendation",
                        reference_id=rec.recommendation_id,
                        description="Live re-check of current vs. recommended provider/model",
                        metrics={
                            "current_live_sample_size": current_stats[0] if current_stats else None,
                            "current_live_pass_rate": current_stats[2] if current_stats else None,
                            "recommended_live_sample_size": recommended_stats[0] if recommended_stats else None,
                            "recommended_live_pass_rate": recommended_stats[2] if recommended_stats else None,
                        },
                    )
                ],
            )
        )
    return findings


def _live_stats(
    db: Session, policy_version: str, task_type: str, task_subcategory: str | None, provider: str, model: str
) -> tuple[int, float, float | None] | None:
    """Fresh (sample_size, average_cost, pass_rate) for one (policy_version,
    task_type, task_subcategory, provider, model) group, queried directly
    from routing_decisions/execution_results/quality_results — NOT from
    routing_patterns. This is what makes recommendation validation
    meaningful rather than circular: routing_patterns and
    optimization_recommendations are only as fresh as the last
    POST /analytics/refresh, but live traffic keeps accumulating in
    routing_decisions in the meantime. Re-deriving straight from the raw
    tables checks the recommendation against what's actually happened
    since, not against the same snapshot it was generated from.
    """
    row = (
        db.query(
            func.count(RoutingDecision.request_id),
            func.avg(ExecutionResult.estimated_cost),
            PASS_RATE,
        )
        .join(ExecutionResult, ExecutionResult.request_id == RoutingDecision.request_id)
        .outerjoin(QualityResult, QualityResult.request_id == RoutingDecision.request_id)
        .filter(
            RoutingDecision.routing_policy_version == policy_version,
            RoutingDecision.task_type == task_type,
            RoutingDecision.task_subcategory == task_subcategory,
            RoutingDecision.selected_provider == provider,
            RoutingDecision.selected_model == model,
        )
        .first()
    )
    if row is None or row[0] == 0:
        return None
    return row[0], row[1], row[2]


def _build_suggested_actions(findings: list[Finding]) -> list[SuggestedAction]:
    actions = []
    for finding in findings:
        if finding.category == "recommendation_validation" and "trustworthy" in finding.summary and "should be" not in finding.summary:
            rec_id = finding.evidence[0].reference_id
            actions.append(
                SuggestedAction(
                    action=f"Review and consider approving recommendation {rec_id}",
                    rationale=finding.summary,
                    related_recommendation_id=rec_id,
                    confidence=finding.confidence,
                )
            )
        elif finding.category == "model_degradation":
            actions.append(
                SuggestedAction(
                    action="Investigate degraded model/task_type pairing before its next policy review",
                    rationale=finding.summary,
                    related_recommendation_id=None,
                    confidence=finding.confidence,
                )
            )
    return actions


def _overall_risk(findings: list[Finding]) -> str:
    if not findings:
        return "low"
    return max((f.risk_level for f in findings), key=lambda r: _RISK_ORDER.get(r, 0))


def _overall_confidence(findings: list[Finding]) -> float:
    if not findings:
        return 1.0
    return round(sum(f.confidence for f in findings) / len(findings), 4)


def _build_executive_summary(findings: list[Finding], risk_level: str) -> str:
    if not findings:
        return "No significant routing issues detected in the current policy_version's history."
    by_category: dict[str, int] = {}
    for f in findings:
        by_category[f.category] = by_category.get(f.category, 0) + 1
    breakdown = ", ".join(f"{count} {category}" for category, count in by_category.items())
    return f"{len(findings)} finding(s) ({breakdown}); overall risk: {risk_level}."
