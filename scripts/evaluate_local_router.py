"""Evaluate the persisted local router without treating AI labels as human evidence."""

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.schemas.routing_decision import RoutingTier
from backend.services.local_semantic_router import LocalSemanticRouter
from backend.services.routing_evaluation import classification_metrics, load_dataset, percentile

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "local_router"
REGRESSIONS = [
    ("What is the capital of France?", RoutingTier.BASIC),
    ("What does HTTP stand for?", RoutingTier.BASIC),
    ("Summarize this technical article.", RoutingTier.STANDARD),
    ("Design a multi-tenant RAG architecture for millions of documents.", RoutingTier.ADVANCED),
    ("Analyze this report and explain whether the trade-off is acceptable.", RoutingTier.STANDARD),
]


def evaluate(artifact_dir: Path = ARTIFACT_DIR, fallback_threshold: float = 0.6) -> dict:
    rows = [row for row in load_dataset() if row.dataset_split == "test"]
    router = LocalSemanticRouter.from_artifact(artifact_dir)
    results = [router.classify(row.prompt) for row in rows]
    metrics = classification_metrics(
        [row.expected_tier for row in rows], [result.routing_tier for result in results],
        [result.raw_confidence for result in results],
    )
    raw_diagnostics = {
        "status": "experimental_against_unreviewed_ai_labels_not_calibration",
        "correctness_brier_score": metrics.pop("correctness_brier_score"),
        "expected_calibration_error": metrics.pop("expected_calibration_error"),
        "confidence_distribution": metrics.pop("confidence_distribution"),
    }
    regressions = []
    for prompt, expected in REGRESSIONS:
        result = router.classify(prompt)
        regressions.append({
            "prompt": prompt, "expected_tier": expected.value, "predicted_tier": result.routing_tier.value,
            "raw_confidence": round(result.raw_confidence, 4), "passed": result.routing_tier is expected,
        })
    latencies = [result.embedding_latency_ms + result.classifier_latency_ms for result in results]
    report = {
        "strategy": "local_semantic", "status": "experimental_unreviewed_labels",
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "test_row_count": len(rows),
        "human_reviewed_test_count": sum(row.review_status in {"human_reviewed", "human_adjudicated"} for row in rows),
        "test_used_for_training_or_tuning": False, **metrics,
        "raw_confidence_diagnostics": raw_diagnostics,
        "calibration_status": "unavailable_insufficient_human_reviewed_validation_data",
        "fallback_threshold": fallback_threshold, "fallback_threshold_status": "experimental_configuration_not_validated",
        "fallback_rate": round(sum(result.raw_confidence < fallback_threshold for result in results) / len(results), 4),
        "local_router_usage_rate": 1.0, "classifier_api_cost": 0.0,
        "classifier_compute_cost": "non-zero infrastructure cost; not measured per request",
        "average_classifier_latency_ms": round(statistics.mean(latencies), 2),
        "p50_classifier_latency_ms": percentile(latencies, .5),
        "p95_classifier_latency_ms": percentile(latencies, .95),
        "quality": None, "generation_cost": None,
        "regressions": regressions, "regressions_passed": all(row["passed"] for row in regressions),
    }
    (artifact_dir / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
