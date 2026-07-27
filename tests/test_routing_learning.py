"""routing_learning.refresh(): pattern aggregation and advisory
recommendation generation. Never touches routing.yaml or the routing
engine — see docs/pr2-analytics.md.
"""

from datetime import datetime, timezone

from backend.database.models import OptimizationRecommendation, RoutingPattern
from backend.schemas.quality import QualityVerdict
from backend.schemas.routing import RoutingResult
from backend.schemas.routing_decision import (
    ReasoningLevel,
    RoutingDecision as RoutingDecisionSchema,
    RoutingDecisionOutcome,
    RoutingTier,
)
from backend.services import routing_learning
from backend.services.decision_service import record


def _record(db, request_id, provider, model, pass_verdict, cost=0.0002, latency=200.0):
    record(
        db,
        request_id=request_id,
        prompt=f"prompt-{request_id}",
        response="answer",
        created_at=datetime.now(timezone.utc),
        decision_outcome=RoutingDecisionOutcome(
            decision=RoutingDecisionSchema(
                routing_tier=RoutingTier.BASIC,
                task_type="Programming",
                reasoning_level=ReasoningLevel.LOW,
                confidence=0.9,
                reason="test",
            ),
            classifier_model="fake",
            latency_ms=1.0,
            input_tokens=1,
            output_tokens=1,
            cost=0.0,
            fallback_used=False,
        ),
        routing_result=RoutingResult(
            provider=provider,
            model=model,
            max_output_tokens=1024,
            tier=RoutingTier.BASIC,
            original_tier=RoutingTier.BASIC,
            escalated=False,
            reasons=["test"],
        ),
        total_latency_ms=latency,
        input_tokens=10,
        output_tokens=10,
        total_cost=cost,
        provider_success=True,
        error_message=None,
        quality_verdict=QualityVerdict(passed=pass_verdict, reason="judged"),
    )


def test_refresh_builds_one_pattern_per_group(db_session):
    _record(db_session, "r1", "google", "gemini-2.5-flash", True)
    _record(db_session, "r2", "google", "gemini-2.5-flash", True)

    result = routing_learning.refresh(db_session)

    assert result.patterns_updated == 1
    pattern = db_session.query(RoutingPattern).one()
    assert pattern.task_type == "Programming"
    assert pattern.provider == "google"
    assert pattern.sample_size == 2
    assert pattern.pass_rate == 1.0
    assert pattern.failure_rate == 0.0


def test_refresh_is_idempotent_wholesale_recompute(db_session):
    _record(db_session, "r1", "google", "gemini-2.5-flash", True)
    routing_learning.refresh(db_session)
    routing_learning.refresh(db_session)

    assert db_session.query(RoutingPattern).count() == 1


def test_refresh_generates_recommendation_when_alternative_outperforms(db_session, monkeypatch):
    # routing.yaml configures google/gemini-2.5-flash for BASIC. Give it a
    # poor pass rate, and give an alternative model at the same tier a much
    # better one with enough samples to clear min_sample_size.
    monkeypatch.setattr(
        routing_learning,
        "load_routing_config",
        lambda: {
            "tiers": {"basic": {"provider": "google", "model": "gemini-2.5-flash"}},
            "policy_version": "v1.0",
            "learning": {"apply_recommendations": False, "min_sample_size": 2, "min_confidence": 0.8},
        },
    )

    for i in range(3):
        _record(db_session, f"bad-{i}", "google", "gemini-2.5-flash", pass_verdict=False)
    for i in range(3):
        _record(db_session, f"good-{i}", "openrouter", "mistralai/mistral-small-3.2-24b-instruct", pass_verdict=True)

    result = routing_learning.refresh(db_session)

    assert result.recommendations_generated == 1
    rec = db_session.query(OptimizationRecommendation).one()
    assert rec.current_provider == "google"
    assert rec.recommended_provider == "openrouter"
    assert rec.status == "pending"
    assert rec.expected_quality_change > 0
    assert rec.policy_version == "v1.0"
    assert rec.evidence["current"]["sample_size"] == 3
    assert rec.evidence["recommended"]["sample_size"] == 3
    assert rec.evidence["recommended"]["pass_rate"] == 1.0


def test_refresh_ignores_patterns_from_a_different_policy_version(db_session, monkeypatch):
    """A pattern recorded under an old policy_version must never generate a
    recommendation against the current one — see PR2 review note on
    policy_version attribution."""
    monkeypatch.setattr(
        routing_learning,
        "load_routing_config",
        lambda: {
            "policy_version": "v2.0",  # active policy — no requests recorded under it yet
            "tiers": {"basic": {"provider": "google", "model": "gemini-2.5-flash"}},
            "learning": {"apply_recommendations": False, "min_sample_size": 2, "min_confidence": 0.8},
        },
    )

    for i in range(3):
        _record(db_session, f"bad-{i}", "google", "gemini-2.5-flash", pass_verdict=False)
    for i in range(3):
        _record(db_session, f"good-{i}", "openrouter", "mistralai/mistral-small-3.2-24b-instruct", pass_verdict=True)

    result = routing_learning.refresh(db_session)

    # patterns are still built (they're tagged with the policy_version each
    # request actually ran under, "v1.0" from routing_policy_version), but
    # since none match "v2.0", no recommendation should compare across them
    assert result.patterns_updated == 2
    assert result.recommendations_generated == 0


def test_refresh_generates_no_recommendation_below_min_sample_size(db_session, monkeypatch):
    monkeypatch.setattr(
        routing_learning,
        "load_routing_config",
        lambda: {
            "tiers": {"basic": {"provider": "google", "model": "gemini-2.5-flash"}},
            "policy_version": "v1.0",
            "learning": {"apply_recommendations": False, "min_sample_size": 20, "min_confidence": 0.8},
        },
    )

    _record(db_session, "bad-1", "google", "gemini-2.5-flash", pass_verdict=False)
    _record(db_session, "good-1", "openrouter", "mistralai/mistral-small-3.2-24b-instruct", pass_verdict=True)

    result = routing_learning.refresh(db_session)

    assert result.recommendations_generated == 0
