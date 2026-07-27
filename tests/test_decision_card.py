"""get_decision_card(): deterministic DecisionCard reconstruction plus
recommendation matching. Covers PR3 requirement #7's cases: normal
routing, no recommendation, recommendation exists, wrong policy_version,
wrong provider/model, serialization.
"""

from datetime import datetime, timezone

from backend.database.models import OptimizationRecommendation
from backend.schemas.decision_card import DecisionDetailResponse
from backend.schemas.routing import RoutingResult
from backend.schemas.routing_decision import (
    ReasoningLevel,
    RoutingDecision as RoutingDecisionSchema,
    RoutingDecisionOutcome,
    RoutingTier,
)
from backend.services.decision_service import get_decision_card, record


def _record(db, request_id="req-1", escalated=False, task_type="Arithmetic"):
    record(
        db,
        request_id=request_id,
        prompt="what is 2+2",
        response="4",
        created_at=datetime.now(timezone.utc),
        decision_outcome=RoutingDecisionOutcome(
            decision=RoutingDecisionSchema(
                routing_tier=RoutingTier.BASIC,
                task_type=task_type,
                reasoning_level=ReasoningLevel.LOW,
                confidence=0.55 if escalated else 0.95,
                reason="Simple arithmetic question",
            ),
            classifier_model="gemini-2.5-flash",
            latency_ms=12.0,
            input_tokens=8,
            output_tokens=6,
            cost=0.0001,
            fallback_used=False,
        ),
        routing_result=RoutingResult(
            provider="google",
            model="gemini-2.5-flash",
            max_output_tokens=1024,
            tier=RoutingTier.STANDARD if escalated else RoutingTier.BASIC,
            original_tier=RoutingTier.BASIC,
            escalated=escalated,
            reasons=(
                ["Simple, short prompt", "Escalated from BASIC due to low classifier confidence (0.55)"]
                if escalated
                else ["Simple, short prompt"]
            ),
        ),
        total_latency_ms=250.0,
        input_tokens=8,
        output_tokens=6,
        total_cost=0.0002,
        provider_success=True,
        error_message=None,
        quality_verdict=None,
    )


def _add_recommendation(db, **overrides):
    defaults = dict(
        task_type="Arithmetic",
        task_subcategory=None,
        policy_version="v1.0",
        current_provider="google",
        recommended_provider="openrouter",
        current_model="gemini-2.5-flash",
        recommended_model="mistralai/mistral-small-3.2-24b-instruct",
        expected_cost_change=0.0001,
        expected_quality_change=0.1,
        confidence=0.9,
        reason="Alternative model performs better",
        evidence={"current": {}, "recommended": {}},
        status="pending",
    )
    defaults.update(overrides)
    db.add(OptimizationRecommendation(**defaults))
    db.commit()


def test_get_decision_card_returns_none_for_unknown_request(db_session):
    assert get_decision_card(db_session, "does-not-exist") is None


def test_normal_routing_no_recommendation(db_session):
    _record(db_session)

    card, recommendation = get_decision_card(db_session, "req-1")

    assert card.request_id == "req-1"
    assert card.policy_version == "v1.0"
    assert card.selected_tier == "BASIC"
    assert card.selected_provider == "google"
    assert card.selected_model == "gemini-2.5-flash"
    assert card.recommendation_available is False
    assert card.recommendation_id is None
    assert recommendation is None
    assert [step.description for step in card.reasoning_steps][-1] == "Final routing complete"


def test_escalation_reflected_in_reasoning_steps(db_session):
    _record(db_session, escalated=True)

    card, _ = get_decision_card(db_session, "req-1")

    assert card.selected_tier == "STANDARD"
    joined = " ".join(step.description for step in card.reasoning_steps)
    assert "Escalated to STANDARD tier" in joined


def test_recommendation_available_when_fully_matching(db_session):
    _record(db_session)
    _add_recommendation(db_session)

    card, recommendation = get_decision_card(db_session, "req-1")

    assert card.recommendation_available is True
    assert card.recommendation_id is not None
    assert recommendation is not None
    assert recommendation.recommended_provider == "openrouter"
    assert recommendation.summary == "Alternative model performs better"


def test_recommendation_ignored_when_policy_version_differs(db_session):
    _record(db_session)
    _add_recommendation(db_session, policy_version="v2.0")

    card, recommendation = get_decision_card(db_session, "req-1")

    assert card.recommendation_available is False
    assert card.recommendation_id is None
    assert recommendation is None


def test_recommendation_ignored_when_provider_model_differs(db_session):
    _record(db_session)
    _add_recommendation(db_session, current_provider="openrouter", current_model="deepseek/deepseek-r1")

    card, recommendation = get_decision_card(db_session, "req-1")

    assert card.recommendation_available is False
    assert recommendation is None


def test_decision_card_serializes_to_expected_json_shape(db_session):
    _record(db_session)
    _add_recommendation(db_session)

    card, recommendation = get_decision_card(db_session, "req-1")
    response = DecisionDetailResponse(decision_card=card, recommendation=recommendation)

    payload = response.model_dump(mode="json")
    assert set(payload.keys()) == {"decision_card", "recommendation"}
    assert payload["decision_card"]["recommendation_available"] is True
    assert payload["recommendation"]["recommendation_id"] == payload["decision_card"]["recommendation_id"]
    assert isinstance(payload["decision_card"]["reasoning_steps"], list)
    assert payload["decision_card"]["reasoning_steps"][0]["step"] == 1
