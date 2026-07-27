"""Engineering hardening pass: failure-path coverage.

Covers the four scenarios called out for this hardening pass:
- a provider call raising (timeout, connection error, or any other
  exception) never leaves the request unaudited
- a model missing a pricing.yaml entry is caught, not a bare 500 with no
  audit trail
- the heuristic classifier fallback no longer forces an unwanted
  escalation (the confidence-vs-threshold bug fixed in this pass)
- startup configuration validation catches bad routing.yaml/pricing.yaml
  before the app serves traffic

All offline — no network access, no API keys required.
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.routers.chat as chat_module
import backend.utils.startup_validation as startup_validation
from backend.database.db import Base, get_db
from backend.database.models import FailedRequest
from backend.main import app
from backend.schemas.quality import QualityVerdict
from backend.schemas.routing_decision import (
    ReasoningLevel,
    RoutingDecision as RoutingDecisionSchema,
    RoutingDecisionOutcome,
    RoutingTier,
)
from backend.services.classifier_service import get_classifier_service
from backend.services.heuristic_classifier import classify_heuristically
from backend.services.providers.base import ProviderResponse
from backend.services.quality_verifier import get_quality_verifier
from backend.utils.config import Settings
from backend.utils.startup_validation import StartupConfigError, validate_startup_config


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


class _RaisingProvider:
    def __init__(self, exc: Exception):
        self._exc = exc

    def generate(
        self, prompt: str, model: str, max_tokens: int = 1024, response_format: str | None = None
    ) -> ProviderResponse:
        raise self._exc


class _WorkingProvider:
    def generate(
        self, prompt: str, model: str, max_tokens: int = 1024, response_format: str | None = None
    ) -> ProviderResponse:
        return ProviderResponse(text="4", input_tokens=8, output_tokens=2)


@pytest.fixture()
def client_factory(monkeypatch):
    """Same shape as test_api_regression's `client` fixture, but lets each
    test choose its own fake provider so it can force a specific failure
    stage instead of the happy path.
    """

    def _make(provider):
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
        monkeypatch.setattr(chat_module, "get_provider", lambda name, settings: provider)

        return TestClient(app), session_factory

    yield _make
    app.dependency_overrides.clear()


def _failed_request_row(session_factory, request_id: str) -> FailedRequest | None:
    db = session_factory()
    try:
        return db.get(FailedRequest, request_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. Provider exception (timeout / connection error / any other exception)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        httpx.TimeoutException("provider timed out"),
        httpx.ConnectError("connection refused"),
        RuntimeError("provider blew up"),
    ],
)
def test_provider_exception_persists_failed_request(client_factory, exc):
    client, session_factory = client_factory(_RaisingProvider(exc))

    response = client.post("/chat", json={"prompt": "what is 2+2"})

    assert response.status_code == 502
    # The client never learns the request_id on a failure response (no
    # successful ChatResponse was built to carry it), so assert against
    # the one row that was written instead of a specific id.
    db = session_factory()
    try:
        rows = db.query(FailedRequest).all()
    finally:
        db.close()
    assert len(rows) == 1
    row = rows[0]
    assert row.stage == "provider_call"
    assert row.provider == "google"
    assert row.model == "gemini-2.5-flash"
    assert row.status == "failed"
    assert row.prompt == "what is 2+2"
    assert str(exc) in row.error_message


def test_provider_exception_does_not_write_a_routing_decision(client_factory):
    client, session_factory = client_factory(_RaisingProvider(RuntimeError("boom")))

    client.post("/chat", json={"prompt": "what is 2+2"})

    history = client.get("/history")
    assert history.status_code == 200
    assert history.json() == []  # a failed request must never appear as a successful one


# ---------------------------------------------------------------------------
# 2. Missing pricing configuration
# ---------------------------------------------------------------------------


def test_missing_pricing_config_persists_failed_request(client_factory, monkeypatch):
    import backend.services.cost_estimator as cost_estimator_module

    monkeypatch.setattr(cost_estimator_module, "load_pricing_config", lambda: {"models": {}})

    client, session_factory = client_factory(_WorkingProvider())
    response = client.post("/chat", json={"prompt": "what is 2+2"})

    assert response.status_code == 502
    db = session_factory()
    try:
        rows = db.query(FailedRequest).all()
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0].stage == "cost_estimation"
    assert rows[0].model == "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# 3. Classifier fallback / heuristic confidence bug fix
# ---------------------------------------------------------------------------


def test_heuristic_fallback_confidence_does_not_force_escalation():
    """Regression test for the bug found in this hardening pass: a fixed
    confidence of 0.5 sat below routing.yaml's default `low` threshold
    (0.6), so routing_engine.select() escalated every single fallback
    decision past the tier the word count itself picked. The fallback's
    confidence must now clear the configured `low` threshold.
    """
    from backend.utils.yaml_config import load_routing_config

    settings = Settings(easy_max_words=30, medium_max_words=100)
    decision = classify_heuristically("short prompt", settings)

    low = load_routing_config()["confidence_thresholds"]["low"]
    assert decision.confidence >= low
    assert decision.routing_tier == RoutingTier.BASIC


def test_heuristic_fallback_still_below_high_confidence_threshold():
    from backend.utils.yaml_config import load_routing_config

    settings = Settings(easy_max_words=30, medium_max_words=100)
    decision = classify_heuristically("short prompt", settings)

    high = load_routing_config()["confidence_thresholds"]["high"]
    assert decision.confidence < high


def test_classifier_falls_back_to_heuristic_on_provider_exception():
    from backend.services.classifier_service import ClassifierService

    settings = Settings(google_api_key="", openrouter_api_key="")  # no client ready -> forces fallback
    service = ClassifierService(settings)

    outcome = service.classify("what is 2+2")

    assert outcome.fallback_used is True
    assert outcome.classifier_model == "heuristic"
    assert outcome.cost == 0.0


# ---------------------------------------------------------------------------
# 4. Startup configuration validation
# ---------------------------------------------------------------------------


_VALID_ROUTING_CONFIG = {
    "policy_version": "v1.0",
    "classifier": {"provider": "openrouter", "model": "m1", "max_output_tokens": 512},
    "confidence_thresholds": {"low": 0.6, "high": 0.9, "escalate_on_low_confidence": True},
    "tiers": {
        "basic": {"provider": "google", "model": "m1", "max_output_tokens": 1024},
        "standard": {"provider": "openrouter", "model": "m1", "max_output_tokens": 1536},
        "advanced": {"provider": "openrouter", "model": "m2", "max_output_tokens": 4096},
    },
    "learning": {"apply_recommendations": False, "min_sample_size": 20, "min_confidence": 0.8},
}
_VALID_PRICING_CONFIG = {
    "models": {
        "m1": {"provider": "openrouter", "input_per_million": 0.1, "output_per_million": 0.3},
        "m2": {"provider": "openrouter", "input_per_million": 0.5, "output_per_million": 2.0},
    }
}


def test_startup_validation_passes_on_valid_config(monkeypatch):
    monkeypatch.setattr(startup_validation, "load_routing_config", lambda: _VALID_ROUTING_CONFIG)
    monkeypatch.setattr(startup_validation, "load_pricing_config", lambda: _VALID_PRICING_CONFIG)

    validate_startup_config()  # must not raise


def test_startup_validation_fails_on_model_missing_pricing(monkeypatch):
    monkeypatch.setattr(startup_validation, "load_routing_config", lambda: _VALID_ROUTING_CONFIG)
    monkeypatch.setattr(startup_validation, "load_pricing_config", lambda: {"models": {}})

    with pytest.raises(StartupConfigError, match="no pricing.yaml entry"):
        validate_startup_config()


def test_startup_validation_fails_on_unknown_provider(monkeypatch):
    bad_config = {
        **_VALID_ROUTING_CONFIG,
        "tiers": {
            **_VALID_ROUTING_CONFIG["tiers"],
            "basic": {"provider": "openai", "model": "m1", "max_output_tokens": 1024},
        },
    }
    monkeypatch.setattr(startup_validation, "load_routing_config", lambda: bad_config)
    monkeypatch.setattr(startup_validation, "load_pricing_config", lambda: _VALID_PRICING_CONFIG)

    with pytest.raises(StartupConfigError, match="not one of"):
        validate_startup_config()


def test_startup_validation_fails_on_inverted_thresholds(monkeypatch):
    bad_config = {
        **_VALID_ROUTING_CONFIG,
        "confidence_thresholds": {"low": 0.9, "high": 0.6, "escalate_on_low_confidence": True},
    }
    monkeypatch.setattr(startup_validation, "load_routing_config", lambda: bad_config)
    monkeypatch.setattr(startup_validation, "load_pricing_config", lambda: _VALID_PRICING_CONFIG)

    with pytest.raises(StartupConfigError, match="confidence_thresholds"):
        validate_startup_config()


def test_startup_validation_fails_on_missing_tier(monkeypatch):
    bad_config = {**_VALID_ROUTING_CONFIG, "tiers": {"basic": _VALID_ROUTING_CONFIG["tiers"]["basic"]}}
    monkeypatch.setattr(startup_validation, "load_routing_config", lambda: bad_config)
    monkeypatch.setattr(startup_validation, "load_pricing_config", lambda: _VALID_PRICING_CONFIG)

    with pytest.raises(StartupConfigError, match="tiers.standard is missing"):
        validate_startup_config()


def test_startup_validation_reports_multiple_errors_at_once(monkeypatch):
    bad_config = {
        **_VALID_ROUTING_CONFIG,
        "confidence_thresholds": {"low": 0.9, "high": 0.6, "escalate_on_low_confidence": True},
        "learning": {"apply_recommendations": False, "min_sample_size": 0, "min_confidence": 0.8},
    }
    monkeypatch.setattr(startup_validation, "load_routing_config", lambda: bad_config)
    monkeypatch.setattr(startup_validation, "load_pricing_config", lambda: {"models": {}})

    with pytest.raises(StartupConfigError) as exc_info:
        validate_startup_config()

    message = str(exc_info.value)
    assert "confidence_thresholds" in message
    assert "min_sample_size" in message
    assert "no pricing.yaml entry" in message


def test_app_startup_validates_current_routing_and_pricing_config():
    """The real routing.yaml/pricing.yaml shipped in this repo must itself
    pass validation — this is what actually runs on every app boot."""
    with TestClient(app):
        pass  # entering the context manager runs the lifespan startup hook
