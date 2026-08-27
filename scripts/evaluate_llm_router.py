"""Run the Mistral routing baseline on the same untouched TEST split."""

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.classifier_service import ClassifierService
from backend.services.routing_evaluation import classification_metrics, load_dataset, percentile
from backend.utils.config import Settings

OUTPUT = Path(__file__).resolve().parents[1] / "artifacts" / "local_router" / "llm_evaluation.json"


def evaluate() -> dict:
    rows = [row for row in load_dataset() if row.dataset_split == "test"]
    classifier = ClassifierService(Settings(router_mode="llm"))
    outcomes, errors = [], []
    for index, row in enumerate(rows, 1):
        try:
            outcomes.append((row, classifier.classify(row.prompt)))
        except Exception as exc:
            errors.append({"prompt_id": row.prompt_id, "error": str(exc)})
        if index % 10 == 0:
            print(f"evaluated {index}/{len(rows)}", flush=True)

    metrics = classification_metrics(
        [row.expected_tier for row, _ in outcomes],
        [outcome.decision.routing_tier for _, outcome in outcomes],
        [outcome.decision.confidence for _, outcome in outcomes],
    )
    raw_diagnostics = {
        "status": "experimental_against_unreviewed_ai_labels_not_calibration",
        "correctness_brier_score": metrics.pop("correctness_brier_score"),
        "expected_calibration_error": metrics.pop("expected_calibration_error"),
        "confidence_distribution": metrics.pop("confidence_distribution"),
    }
    latencies = [outcome.latency_ms for _, outcome in outcomes]
    costs = [outcome.cost for _, outcome in outcomes]
    report = {
        "strategy": "llm_fallback",
        "status": "experimental_unreviewed_labels" if not errors else "incomplete_provider_errors",
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "test_row_count": len(rows),
        "evaluated_row_count": len(outcomes), "provider_error_count": len(errors), "errors": errors,
        "human_reviewed_test_count": 0, "test_used_for_training_or_tuning": False,
        **metrics, "raw_confidence_diagnostics": raw_diagnostics,
        "calibration_status": "unavailable_insufficient_human_reviewed_validation_data",
        "classifier_api_cost_total": round(sum(costs), 8),
        "classifier_api_cost_average": round(statistics.mean(costs), 8) if costs else None,
        "average_classifier_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
        "p50_classifier_latency_ms": percentile(latencies, .5),
        "p95_classifier_latency_ms": percentile(latencies, .95),
        "external_router_usage_rate": 1.0, "generation_cost": None, "quality": None,
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
