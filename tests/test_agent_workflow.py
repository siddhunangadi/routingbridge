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


class _AdvancedClassifier:
    def classify(self, prompt: str) -> RoutingDecisionOutcome:
        return RoutingDecisionOutcome(
            decision=RoutingDecisionSchema(
                routing_tier=RoutingTier.ADVANCED,
                task_type="Architecture Design",
                reasoning_level=ReasoningLevel.HIGH,
                confidence=0.95,
                reason="Multi-step design problem",
            ),
            classifier_model="fake-classifier",
            latency_ms=5.0,
            input_tokens=5,
            output_tokens=5,
            cost=0.0,
            fallback_used=False,
        )


class _Provider:
    last_prompt = ""

    def generate(
        self, prompt: str, model: str, max_tokens: int = 1024, response_format: str | None = None
    ) -> ProviderResponse:
        self.last_prompt = prompt
        return ProviderResponse(text="answer", input_tokens=8, output_tokens=2)


class _QualityVerifier:
    def verify(self, prompt: str, response: str) -> QualityVerdict:
        return QualityVerdict(passed=True, reason="ok")


def test_advanced_chat_uses_a_short_plan_answer_self_check_workflow(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    provider = _Provider()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_classifier_service] = lambda: _AdvancedClassifier()
    app.dependency_overrides[get_quality_verifier] = lambda: _QualityVerifier()
    monkeypatch.setattr(chat_module, "get_provider", lambda name, settings: provider)

    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={"prompt": "Design a resilient system."})
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    assert "Plan" in provider.last_prompt
    assert "Final answer" in provider.last_prompt
    assert "Self-check" in provider.last_prompt
