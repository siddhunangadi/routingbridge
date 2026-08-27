from backend.schemas.routing_decision import RoutingTier
from backend.services.routing_evaluation import classification_metrics, percentile


def test_classification_metrics_use_literal_three_tier_fixture():
    metrics = classification_metrics(
        [RoutingTier.BASIC, RoutingTier.STANDARD, RoutingTier.ADVANCED, RoutingTier.ADVANCED],
        [RoutingTier.BASIC, RoutingTier.ADVANCED, RoutingTier.ADVANCED, RoutingTier.BASIC],
        [0.9, 0.8, 0.7, 0.6],
    )

    assert metrics["accuracy"] == 0.5
    assert metrics["macro_precision"] == 0.3333
    assert metrics["macro_recall"] == 0.5
    assert metrics["macro_f1"] == 0.3889
    assert metrics["confusion_matrix"] == [[1, 0, 0], [0, 0, 1], [1, 0, 1]]
    assert metrics["under_routing_rate"] == 0.25
    assert metrics["over_routing_rate"] == 0.25
    assert metrics["basic_to_advanced_rate"] == 0.0
    assert metrics["advanced_to_basic_rate"] == 0.25
    assert sum(bucket["count"] for bucket in metrics["confidence_distribution"]) == 4
    assert 0 <= metrics["correctness_brier_score"] <= 1
    assert 0 <= metrics["expected_calibration_error"] <= 1


def test_metrics_handle_zero_examples_without_division_errors():
    metrics = classification_metrics([], [], [])

    assert metrics["accuracy"] is None
    assert metrics["macro_f1"] is None
    assert metrics["under_routing_rate"] is None
    assert metrics["expected_calibration_error"] is None
    assert metrics["confusion_matrix"] == [[0, 0, 0], [0, 0, 0], [0, 0, 0]]


def test_percentile_is_deterministic_for_small_and_empty_samples():
    assert percentile([], 0.95) is None
    assert percentile([1.0], 0.95) == 1.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 3.85
