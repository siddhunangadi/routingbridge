"""decision_service.record(): transactional persistence across the four
normalized tables. DecisionCard reconstruction (get_decision_card) has its
own tests in test_decision_card.py.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from backend.database.models import ExecutionResult, QualityResult, Request, RoutingDecision
from backend.schemas.quality import QualityVerdict
from backend.schemas.routing import RoutingResult
from backend.schemas.routing_decision import (
    ReasoningLevel,
    RoutingDecision as RoutingDecisionSchema,
    RoutingDecisionOutcome,
    RoutingTier,
)
from backend.services import decision_service


def _outcome(confidence: float = 0.95) -> RoutingDecisionOutcome:
    return RoutingDecisionOutcome(
        decision=RoutingDecisionSchema(
            routing_tier=RoutingTier.BASIC,
            task_type="Arithmetic",
            reasoning_level=ReasoningLevel.LOW,
            confidence=confidence,
            reason="Simple arithmetic question",
        ),
        classifier_model="gemini-2.5-flash",
        latency_ms=12.0,
        input_tokens=8,
        output_tokens=6,
        cost=0.0001,
        fallback_used=False,
    )


def _routing_result() -> RoutingResult:
    return RoutingResult(
        provider="google",
        model="gemini-2.5-flash",
        max_output_tokens=1024,
        tier=RoutingTier.BASIC,
        original_tier=RoutingTier.BASIC,
        escalated=False,
        reasons=["Simple, short prompt"],
    )


def test_record_persists_all_four_tables(db_session):
    request_id = "req-1"

    decision_service.record(
        db_session,
        request_id=request_id,
        prompt="what is 2+2",
        response="4",
        created_at=datetime.now(timezone.utc),
        decision_outcome=_outcome(),
        routing_result=_routing_result(),
        total_latency_ms=250.0,
        input_tokens=8,
        output_tokens=6,
        total_cost=0.0002,
        provider_success=True,
        error_message=None,
        quality_verdict=QualityVerdict(passed=True, reason="Correct"),
    )

    req = db_session.get(Request, request_id)
    decision = db_session.get(RoutingDecision, request_id)
    execution = db_session.get(ExecutionResult, request_id)
    quality = db_session.get(QualityResult, request_id)

    assert req is not None and req.prompt == "what is 2+2" and req.response == "4"
    assert decision is not None and decision.selected_model == "gemini-2.5-flash"
    assert execution is not None and execution.estimated_cost == 0.0002
    assert quality is not None and quality.verdict is True


def test_record_skips_quality_result_when_not_verified(db_session):
    request_id = "req-2"

    decision_service.record(
        db_session,
        request_id=request_id,
        prompt="explain quantum computing in depth",
        response="...",
        created_at=datetime.now(timezone.utc),
        decision_outcome=_outcome(),
        routing_result=_routing_result(),
        total_latency_ms=250.0,
        input_tokens=8,
        output_tokens=6,
        total_cost=0.0002,
        provider_success=True,
        error_message=None,
        quality_verdict=None,
    )

    assert db_session.get(QualityResult, request_id) is None
    # the other three tables are still written
    assert db_session.get(Request, request_id) is not None
    assert db_session.get(RoutingDecision, request_id) is not None
    assert db_session.get(ExecutionResult, request_id) is not None


def test_record_rolls_back_on_failure(db_session):
    request_id = "req-3"
    common_kwargs = dict(
        request_id=request_id,
        prompt="dup",
        response="dup",
        created_at=datetime.now(timezone.utc),
        decision_outcome=_outcome(),
        routing_result=_routing_result(),
        total_latency_ms=10.0,
        input_tokens=1,
        output_tokens=1,
        total_cost=0.0001,
        provider_success=True,
        error_message=None,
        quality_verdict=None,
    )

    decision_service.record(db_session, **common_kwargs)

    # Reusing the same request_id violates the requests.request_id primary
    # key: the commit for this second call must fail, and none of ITS rows
    # (across any of the four tables) should be left behind — the first
    # call's row is the only one that should exist afterwards.
    with pytest.raises(IntegrityError):
        decision_service.record(db_session, **common_kwargs)
    db_session.rollback()

    assert db_session.query(Request).filter_by(request_id=request_id).count() == 1
    assert db_session.query(RoutingDecision).filter_by(request_id=request_id).count() == 1
