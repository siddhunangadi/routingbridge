"""Regression coverage for PR1: the public API contracts (/chat, /history,
/stats) must be byte-for-byte the same shape they were before the
RequestLog -> normalized-tables refactor. LLM/provider calls are faked so
these tests need no network access and no API keys.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.routers.chat as chat_module
from backend.database.db import Base, get_db
from backend.main import app
from backend.schemas.quality import QualityVerdict
from backend.schemas.routing_decision import (
    ReasoningLevel,
    RoutingDecision as RoutingDecisionSchema,
    RoutingDecisionOutcome,
    RoutingTier,
)
from backend.services.classifier_service import get_classifier_service
from backend.services.providers.base import ProviderResponse
from backend.services.quality_verifier import get_quality_verifier

EXPECTED_CHAT_KEYS = {
    "request_id", "prompt", "response", "routing_tier", "original_tier",
    "escalated", "task_type", "reasoning_level", "confidence", "routing_reason",
    "classifier_model", "fallback_used", "provider", "model", "input_tokens",
    "output_tokens", "classifier_cost", "model_cost", "total_cost",
    "total_latency_ms", "quality_passed", "quality_reason", "timestamp",
}

EXPECTED_HISTORY_KEYS = {
    "id", "timestamp", "prompt", "response", "routing_tier", "original_tier",
    "escalated", "task_type", "reasoning_level", "confidence", "routing_reason",
    "classifier_model", "fallback_used", "provider", "model", "input_tokens",
    "output_tokens", "classifier_cost", "model_cost", "total_cost",
    "total_latency_ms", "quality_passed", "quality_reason",
}

EXPECTED_STATS_KEYS = {
    "total_requests", "total_cost", "avg_latency_ms", "requests_per_tier",
    "cost_per_model", "estimated_savings", "quality_verified_count",
    "quality_pass_rate",
}


class _FakeClassifier:
    def classify(self, prompt: str) -> RoutingDecisionOutcome:
        return RoutingDecisionOutcome(
            decision=RoutingDecisionSchema(
                routing_tier=RoutingTier.BASIC,
                task_type="Arithmetic",
                reasoning_level=ReasoningLevel.LOW,
                confidence=0.95,
                reason="Simple arithmetic question",
            ),
            classifier_model="fake-classifier",
            latency_ms=5.0,
            input_tokens=5,
            output_tokens=5,
            cost=0.0,
            fallback_used=False,
        )


class _FakeQualityVerifier:
    def verify(self, prompt: str, response: str) -> QualityVerdict:
        return QualityVerdict(passed=True, reason="Correct answer")


class _FakeProvider:
    def generate(self, prompt: str, model: str, max_tokens: int = 1024) -> ProviderResponse:
        return ProviderResponse(text="4", input_tokens=8, output_tokens=2)


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_classifier_service] = lambda: _FakeClassifier()
    app.dependency_overrides[get_quality_verifier] = lambda: _FakeQualityVerifier()
    monkeypatch.setattr(chat_module, "get_provider", lambda name, settings: _FakeProvider())

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    engine.dispose()


def test_chat_response_contract_unchanged(client):
    response = client.post("/chat", json={"prompt": "what is 2+2"})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == EXPECTED_CHAT_KEYS
    assert body["provider"] == "google"
    assert body["model"] == "gemini-2.5-flash"
    assert body["quality_passed"] is True


def test_history_response_contract_unchanged(client):
    client.post("/chat", json={"prompt": "what is 2+2"})

    response = client.get("/history")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert set(items[0].keys()) == EXPECTED_HISTORY_KEYS
    assert items[0]["prompt"] == "what is 2+2"
    assert items[0]["response"] == "4"


def test_stats_response_contract_unchanged(client):
    client.post("/chat", json={"prompt": "what is 2+2"})

    response = client.get("/stats")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == EXPECTED_STATS_KEYS
    assert body["total_requests"] == 1
    assert body["quality_verified_count"] == 1
    assert body["quality_pass_rate"] == 1.0


def test_stats_empty_database_contract_unchanged(client):
    response = client.get("/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["total_requests"] == 0
    assert body["quality_pass_rate"] is None


def test_analytics_endpoints_end_to_end(client):
    client.post("/chat", json={"prompt": "what is 2+2"})

    refresh = client.post("/analytics/refresh")
    assert refresh.status_code == 200
    assert refresh.json()["patterns_updated"] == 1

    routing = client.get("/analytics/routing")
    assert routing.status_code == 200
    assert routing.json()["providers"][0]["provider"] == "google"

    patterns = client.get("/analytics/patterns")
    assert patterns.status_code == 200
    assert len(patterns.json()) == 1

    recommendations = client.get("/analytics/recommendations")
    assert recommendations.status_code == 200
    assert recommendations.json() == []


def test_routing_decision_endpoint(client):
    chat_response = client.post("/chat", json={"prompt": "what is 2+2"})
    request_id = chat_response.json()["request_id"]

    response = client.get(f"/routing/decision/{request_id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"decision_card", "recommendation"}
    assert body["decision_card"]["request_id"] == request_id
    assert body["decision_card"]["selected_provider"] == "google"
    assert body["decision_card"]["recommendation_available"] is False
    assert body["recommendation"] is None


def test_routing_decision_endpoint_404_for_unknown_request(client):
    response = client.get("/routing/decision/does-not-exist")
    assert response.status_code == 404


def test_agent_investigate_report_and_list_endpoints(client):
    client.post("/chat", json={"prompt": "what is 2+2"})

    investigate = client.post("/agent/investigate")
    assert investigate.status_code == 200
    body = investigate.json()
    assert set(body.keys()) == {
        "report_id", "created_at", "policy_version", "executive_summary",
        "findings", "suggested_actions", "risk_level", "confidence",
        "investigation_steps", "tools_used",
    }
    report_id = body["report_id"]

    report = client.get(f"/agent/report/{report_id}")
    assert report.status_code == 200
    assert report.json()["report_id"] == report_id

    reports = client.get("/agent/reports")
    assert reports.status_code == 200
    assert len(reports.json()) == 1
    assert reports.json()[0]["report_id"] == report_id


def test_agent_report_404_for_unknown_id(client):
    response = client.get("/agent/report/does-not-exist")
    assert response.status_code == 404
