from backend.schemas.routing_decision import ReasoningLevel, RoutingDecision, RoutingTier
from backend.services.routing_engine import RoutingEngine


def _decision() -> RoutingDecision:
    return RoutingDecision(
        routing_tier=RoutingTier.BASIC,
        task_type="factual",
        reasoning_level=ReasoningLevel.LOW,
        confidence=0.95,
        reason="simple",
    )


def test_engine_selects_cheapest_healthy_eligible_candidate(monkeypatch):
    config = {
        "confidence_thresholds": {"low": 0.6, "escalate_on_low_confidence": True},
        "tiers": {
            "basic": {
                "reasons": ["sufficient"],
                "candidates": [
                    {"provider": "google", "model": "expensive", "max_output_tokens": 100, "expected_cost": 2, "expected_quality": 0.95, "healthy": True},
                    {"provider": "openrouter", "model": "cheap", "max_output_tokens": 100, "expected_cost": 1, "expected_quality": 0.91, "healthy": True},
                    {"provider": "openrouter", "model": "broken", "max_output_tokens": 100, "expected_cost": 0, "expected_quality": 0.99, "healthy": False},
                ],
                "minimum_quality": 0.90,
            },
            "standard": {"provider": "openrouter", "model": "standard", "max_output_tokens": 100, "reasons": []},
            "advanced": {"provider": "openrouter", "model": "advanced", "max_output_tokens": 100, "reasons": []},
        },
    }
    monkeypatch.setattr("backend.services.routing_engine.load_routing_config", lambda: config)

    result = RoutingEngine().select(_decision())

    assert result.model == "cheap"
    assert [candidate.model for candidate in result.candidates] == ["cheap", "expensive"]


def test_engine_does_not_second_guess_the_classifier_tier(monkeypatch):
    config = {
        "confidence_thresholds": {"low": 0.6, "escalate_on_low_confidence": True},
        "tiers": {
            "basic": {"provider": "p", "model": "basic", "max_output_tokens": 1, "reasons": []},
            "standard": {"provider": "p", "model": "standard", "max_output_tokens": 1, "reasons": []},
            "advanced": {"provider": "p", "model": "advanced", "max_output_tokens": 1, "reasons": []},
        },
    }
    monkeypatch.setattr("backend.services.routing_engine.load_routing_config", lambda: config)

    result = RoutingEngine().select(_decision())

    assert result.tier is RoutingTier.BASIC
    assert result.escalated is False
