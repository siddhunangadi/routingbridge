"""routing_agent.investigate(): the deterministic investigation pipeline.
Covers PR4 requirement #7's cases: investigation generation, anomaly
detection, recommendation validation, report retrieval, serialization.
No LLM call is ever made — see docs/pr4-routing-agent.md.
"""

from datetime import datetime, timezone

from backend.database.models import InvestigationReport as InvestigationReportModel
from backend.schemas.quality import QualityVerdict
from backend.schemas.routing import RoutingResult
from backend.schemas.routing_decision import (
    ReasoningLevel,
    RoutingDecision as RoutingDecisionSchema,
    RoutingDecisionOutcome,
    RoutingTier,
)
from backend.services import investigation_service, routing_agent, routing_learning
from backend.services.decision_service import record

_LOWERED_THRESHOLD_CONFIG = {
    "policy_version": "v2.1",
    "tiers": {"basic": {"provider": "google", "model": "gemini-2.5-flash"}},
    "learning": {"apply_recommendations": False, "min_sample_size": 2, "min_confidence": 0.8},
}


def _record(db, request_id, task_type, provider, model, passed, cost=0.0002, latency=200.0):
    record(
        db,
        request_id=request_id,
        prompt=f"prompt-{request_id}",
        response="answer",
        created_at=datetime.now(timezone.utc),
        decision_outcome=RoutingDecisionOutcome(
            decision=RoutingDecisionSchema(
                routing_tier=RoutingTier.BASIC,
                task_type=task_type,
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
        quality_verdict=None if passed is None else QualityVerdict(passed=passed, reason="judged"),
    )


def test_investigation_with_no_data_reports_low_risk(db_session):
    report = routing_agent.investigate(db_session)

    assert report.findings == []
    assert report.risk_level == "low"
    assert report.confidence == 1.0
    assert "No significant" in report.executive_summary
    assert report.tools_used  # still records what it looked at, even finding nothing


def test_investigation_never_writes_routing_tables(db_session, monkeypatch):
    from backend.database.models import OptimizationRecommendation, RoutingPattern

    monkeypatch.setattr(routing_learning, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)
    monkeypatch.setattr(routing_agent, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)

    for i in range(5):
        _record(db_session, f"deg-{i}", "Programming", "google", "gemini-2.5-flash", passed=False)
    routing_learning.refresh(db_session)

    patterns_before = db_session.query(RoutingPattern).count()
    recs_before = db_session.query(OptimizationRecommendation).count()

    routing_agent.investigate(db_session)

    assert db_session.query(RoutingPattern).count() == patterns_before
    assert db_session.query(OptimizationRecommendation).count() == recs_before


def test_detects_degraded_task_type(db_session, monkeypatch):
    monkeypatch.setattr(routing_learning, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)
    monkeypatch.setattr(routing_agent, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)

    for i in range(5):
        _record(db_session, f"deg-{i}", "Programming", "google", "gemini-2.5-flash", passed=False)
    routing_learning.refresh(db_session)

    report = routing_agent.investigate(db_session)

    degradation_findings = [f for f in report.findings if f.category == "model_degradation"]
    assert len(degradation_findings) == 1
    assert "Programming" in degradation_findings[0].summary
    assert report.risk_level == "high"


def test_detects_cost_anomaly_across_days(db_session, monkeypatch):
    monkeypatch.setattr(routing_agent, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)

    _record(db_session, "day1-a", "Programming", "google", "gemini-2.5-flash", passed=True, cost=0.0001)
    _record(db_session, "day1-b", "Programming", "google", "gemini-2.5-flash", passed=True, cost=0.0001)

    # simulate a second, much more expensive day by backdating one row's Request/ExecutionResult day
    from backend.database.models import Request

    _record(db_session, "day2-a", "Programming", "google", "gemini-2.5-flash", passed=True, cost=0.01)
    older = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.query(Request).filter(Request.request_id.in_(["day1-a", "day1-b"])).update(
        {Request.created_at: older}, synchronize_session=False
    )
    db_session.commit()

    report = routing_agent.investigate(db_session)

    anomaly_findings = [f for f in report.findings if f.category == "cost_trend"]
    assert len(anomaly_findings) == 1


def test_validates_recommendation_as_trustworthy(db_session, monkeypatch):
    monkeypatch.setattr(routing_learning, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)
    monkeypatch.setattr(routing_agent, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)

    for i in range(3):
        _record(db_session, f"bad-{i}", "Programming", "google", "gemini-2.5-flash", passed=False)
    for i in range(3):
        _record(db_session, f"good-{i}", "Programming", "openrouter", "mistralai/mistral-small-3.2-24b-instruct", passed=True)
    routing_learning.refresh(db_session)

    report = routing_agent.investigate(db_session)

    validations = [f for f in report.findings if f.category == "recommendation_validation"]
    assert len(validations) == 1
    assert "is trustworthy" in validations[0].summary

    actions = [a for a in report.suggested_actions if a.related_recommendation_id]
    assert len(actions) == 1


def test_validates_recommendation_as_stale_when_live_data_no_longer_supports_it(db_session, monkeypatch):
    monkeypatch.setattr(routing_learning, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)
    monkeypatch.setattr(routing_agent, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)

    for i in range(3):
        _record(db_session, f"bad-{i}", "Programming", "google", "gemini-2.5-flash", passed=False)
    for i in range(3):
        _record(db_session, f"good-{i}", "Programming", "openrouter", "mistralai/mistral-small-3.2-24b-instruct", passed=True)
    routing_learning.refresh(db_session)

    # new live traffic reverses the picture: google now passes, openrouter now fails
    for i in range(3, 6):
        _record(db_session, f"bad-{i}", "Programming", "google", "gemini-2.5-flash", passed=True)
    for i in range(3, 6):
        _record(db_session, f"good-{i}", "Programming", "openrouter", "mistralai/mistral-small-3.2-24b-instruct", passed=False)

    report = routing_agent.investigate(db_session)

    validations = [f for f in report.findings if f.category == "recommendation_validation"]
    assert len(validations) == 1
    assert "should be re-reviewed" in validations[0].summary
    assert not any(a.related_recommendation_id for a in report.suggested_actions)


def test_report_is_persisted_and_retrievable(db_session):
    report = routing_agent.investigate(db_session)

    stored = db_session.get(InvestigationReportModel, report.report_id)
    assert stored is not None
    assert stored.policy_version == report.policy_version

    fetched = investigation_service.get_report(db_session, report.report_id)
    # SQLite round-trips DateTime as naive, dropping the tzinfo `report`
    # was built with in-process — same benign artifact PR1 hit with
    # Request.created_at. Compare everything except that field directly.
    assert fetched.model_dump(exclude={"created_at"}) == report.model_dump(exclude={"created_at"})

    summaries = investigation_service.list_reports(db_session, limit=10, offset=0)
    assert len(summaries) == 1
    assert summaries[0].report_id == report.report_id


def test_get_report_returns_none_for_unknown_id(db_session):
    assert investigation_service.get_report(db_session, "does-not-exist") is None


def test_report_serializes_to_expected_json_shape(db_session, monkeypatch):
    monkeypatch.setattr(routing_learning, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)
    monkeypatch.setattr(routing_agent, "load_routing_config", lambda: _LOWERED_THRESHOLD_CONFIG)

    for i in range(5):
        _record(db_session, f"deg-{i}", "Programming", "google", "gemini-2.5-flash", passed=False)
    routing_learning.refresh(db_session)

    report = routing_agent.investigate(db_session)
    payload = report.model_dump(mode="json")

    assert set(payload.keys()) >= {
        "report_id", "created_at", "policy_version", "executive_summary",
        "findings", "suggested_actions", "risk_level", "confidence",
        "investigation_steps", "tools_used",
    }
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["findings"][0]["evidence"], list)
