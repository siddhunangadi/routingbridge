from backend.services.routing_evaluation import benchmark, release_gate, run_regressions
from backend.schemas.routing_decision import ReasoningLevel, RoutingDecision, RoutingDecisionOutcome, RoutingTier


def test_benchmark_refuses_to_invent_missing_evidence():
    result = benchmark()

    assert result["dataset"]["human_reviewed"] == 0
    assert result["dataset"]["evidence_status"] == "validation_incomplete"
    assert result["calibration_status"].startswith("unavailable")
    assert {row["strategy"] for row in result["strategies"]} == {
        "always_basic", "always_standard", "always_advanced", "heuristic_historical",
        "llm_fallback", "local_semantic",
    }
    local = next(row for row in result["strategies"] if row["strategy"] == "local_semantic")
    assert local["status"] == "experimental_unreviewed_labels"
    assert result["historical_synthetic_benchmark"]["generalization_valid"] is False


def test_production_gate_blocks_insufficient_evidence():
    gate = release_gate(benchmark())

    assert gate["allowed"] is False
    assert gate["current_state"] == "VALIDATION"
    assert gate["production_policy_frozen"] is False
    assert gate["checks"]["human_reviewed_evidence"] is False
    assert gate["checks"]["confidence_calibration"] is False

    leaked = benchmark()
    leaked["dataset"]["group_leakage"] = True
    assert release_gate(leaked)["checks"]["group_leakage"] is False


def test_france_is_a_permanent_independent_regression():
    class BasicClassifier:
        def classify(self, prompt):
            return RoutingDecisionOutcome(
                decision=RoutingDecision(routing_tier=RoutingTier.BASIC, task_type="factual",
                    reasoning_level=ReasoningLevel.LOW, confidence=.9, reason="single fact"),
                classifier_model="test", latency_ms=0, input_tokens=0, output_tokens=0,
                cost=0, fallback_used=False,
            )

    result = run_regressions(BasicClassifier())
    france = next(item for item in result["results"] if item["prompt"] == "What is the capital of France?")
    assert france["passed"] is True
