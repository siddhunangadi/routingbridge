import pytest

from backend.schemas.routing_decision import RoutingTier
from backend.services.classifier_service import ClassifierService, RoutingClassifierError
from backend.services.local_semantic_router import LocalRoutingDiagnostic
from backend.services.providers.base import ProviderResponse
from backend.utils.config import Settings


class _Local:
    def __init__(self, confidence=0.9, error=None):
        self.confidence = confidence
        self.error = error
        self.calls = 0

    def classify(self, _prompt):
        self.calls += 1
        if self.error:
            raise self.error
        return LocalRoutingDiagnostic(
            routing_tier=RoutingTier.BASIC, p_basic=self.confidence,
            p_standard=(1 - self.confidence) / 2, p_advanced=(1 - self.confidence) / 2,
            raw_confidence=self.confidence, embedding_dimension=384, embedding_valid=True,
            classifier_artifact_version="test",
        )


class _Mistral:
    def __init__(self, text=None):
        self.text = text or (
            '{"routing_tier":"STANDARD","task_type":"summary",'
            '"reasoning_level":"Medium","confidence":0.8,"reason":"needs synthesis"}'
        )
        self.calls = 0

    def generate(self, *_args, **_kwargs):
        self.calls += 1
        return ProviderResponse(text=self.text, input_tokens=20, output_tokens=10)


def _settings(**changes):
    return Settings(router_mode="local", local_router_fallback_threshold=0.6, **changes)


def test_high_confidence_local_result_avoids_mistral():
    local, mistral = _Local(0.9), _Mistral()

    result = ClassifierService(_settings(), local_router=local, provider=mistral).classify("prompt")

    assert result.classifier_source == "local_semantic"
    assert result.decision.routing_tier is RoutingTier.BASIC
    assert result.fallback_used is False
    assert result.cost == 0
    assert mistral.calls == 0


def test_low_confidence_local_result_uses_validated_mistral_fallback():
    result = ClassifierService(
        _settings(), local_router=_Local(0.59), provider=_Mistral(),
    ).classify("prompt")

    assert result.classifier_source == "llm_fallback"
    assert result.decision.routing_tier is RoutingTier.STANDARD
    assert result.fallback_used is True
    assert "below experimental threshold" in result.fallback_reason
    assert result.p_basic == pytest.approx(0.59)
    assert result.p_standard == pytest.approx(0.205)
    assert result.p_advanced == pytest.approx(0.205)
    assert result.cost > 0


def test_local_inference_failure_uses_mistral_fallback():
    result = ClassifierService(
        _settings(), local_router=_Local(error=RuntimeError("broken embedding")), provider=_Mistral(),
    ).classify("prompt")

    assert result.classifier_source == "llm_fallback"
    assert "broken embedding" in result.fallback_reason


def test_unusable_local_probabilities_do_not_break_mistral_fallback():
    result = ClassifierService(
        _settings(), local_router=_Local(float("nan")), provider=_Mistral(),
    ).classify("prompt")

    assert result.classifier_source == "llm_fallback"
    assert result.p_basic is None


def test_both_routers_failing_is_controlled_and_never_guesses():
    service = ClassifierService(
        _settings(), local_router=_Local(error=RuntimeError("local failed")), provider=_Mistral("not json"),
    )

    with pytest.raises(RoutingClassifierError, match="Local router failed.*Mistral routing fallback failed"):
        service.classify("prompt")


def test_frozen_llm_mode_does_not_call_local_router():
    local = _Local()
    result = ClassifierService(Settings(router_mode="llm"), local_router=local, provider=_Mistral()).classify("prompt")

    assert result.classifier_source == "llm_fallback"
    assert result.fallback_used is False
    assert local.calls == 0
