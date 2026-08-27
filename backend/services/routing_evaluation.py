"""Honest routing evidence: review, leakage checks, metrics, and release gates."""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas.routing_decision import ReasoningLevel, RoutingTier

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "data" / "routing_regressions.jsonl"
TIERS = list(RoutingTier)
REVIEWED = {"human_reviewed", "human_adjudicated"}


class Review(BaseModel):
    reviewer: str = Field(min_length=1)
    proposed_tier: RoutingTier | None
    action: Literal["approve", "change", "ambiguous", "adjudicate"]
    timestamp: datetime
    notes: str | None = None


class RoutingExample(BaseModel):
    prompt_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    expected_tier: RoutingTier
    task_type: str = Field(min_length=1)
    reasoning_level: ReasoningLevel
    prompt_family: str = Field(min_length=1)
    source: Literal["authored", "synthetic", "machine_labeled", "production_regression"]
    review_status: Literal[
        "unreviewed", "pending_human_review", "human_reviewed", "ambiguous",
        "needs_adjudication", "human_adjudicated", "pending_owner_review",
    ]
    provenance: str = "legacy_unreviewed"
    dataset_version: str = "routing-regressions-v1"
    reviewer: str | None = None
    review_timestamp: datetime | None = None
    review_notes: str | None = None
    adjudication_status: Literal["not_required", "needs_adjudication", "adjudicated"]
    dataset_split: Literal["unassigned", "train", "validation", "test"]
    critical: bool = False
    reviews: list[Review] = Field(default_factory=list)
    predicted_tier: RoutingTier | None = None
    predicted_confidence: float | None = Field(default=None, ge=0, le=1)
    predicted_task_type: str | None = None
    predicted_reasoning_level: ReasoningLevel | None = None
    classifier_reason: str | None = None
    selected_model: str | None = None
    selected_provider: str | None = None
    quality_outcome: bool | None = None
    generation_cost: float | None = Field(default=None, ge=0)
    generation_latency_ms: float | None = Field(default=None, ge=0)
    fallback_used: bool | None = None
    provider_failed: bool | None = None


def load_dataset(path: Path = DATASET_PATH) -> list[RoutingExample]:
    rows = [RoutingExample.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [row.prompt_id for row in rows]
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate prompt_id values: {', '.join(duplicates)}")
    validate_group_splits(rows)
    return rows


def write_dataset(rows: list[RoutingExample], path: Path = DATASET_PATH) -> None:
    validate_group_splits(rows)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(f"{row.model_dump_json()}\n" for row in rows))
    temporary.replace(path)


def validate_group_splits(rows: list[RoutingExample]) -> None:
    splits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.dataset_split != "unassigned":
            splits[row.prompt_family].add(row.dataset_split)
    leaked = sorted(family for family, values in splits.items() if len(values) > 1)
    if leaked:
        raise ValueError(f"Group leakage across dataset splits: {', '.join(leaked)}")


def assign_group_splits(rows: list[RoutingExample], seed: int = 42) -> list[RoutingExample]:
    families = sorted({row.prompt_family for row in rows})
    if len(families) < 3:
        raise ValueError("At least three prompt families are required")
    random.Random(seed).shuffle(families)
    train_end, validation_end = round(len(families) * .7), round(len(families) * .85)
    assignments = {
        family: "train" if i < train_end else "validation" if i < validation_end else "test"
        for i, family in enumerate(families)
    }
    result = [row.model_copy(update={"dataset_split": assignments[row.prompt_family]}) for row in rows]
    validate_group_splits(result)
    return result


def review_example(
    example: RoutingExample, *, reviewer: str, action: str,
    expected_tier: RoutingTier | None = None, notes: str | None = None,
    timestamp: datetime | None = None,
) -> RoutingExample:
    if not reviewer.strip() or action in {"change", "adjudicate"} and expected_tier is None:
        raise ValueError("reviewer and any changed expected_tier are required")
    if action == "adjudicate" and example.adjudication_status != "needs_adjudication":
        raise ValueError("Only disputed examples can be adjudicated")
    now = timestamp or datetime.now(timezone.utc)
    proposed = expected_tier if action in {"change", "adjudicate"} else example.expected_tier
    review = Review(reviewer=reviewer, proposed_tier=None if action == "ambiguous" else proposed,
                    action=action, timestamp=now, notes=notes)
    prior = {item.proposed_tier for item in example.reviews if item.proposed_tier is not None}
    disputed = action == "ambiguous" or bool(prior and proposed not in prior)
    status = "human_adjudicated" if action == "adjudicate" else "needs_adjudication" if disputed else "human_reviewed"
    return example.model_copy(update={
        "expected_tier": example.expected_tier if disputed else proposed, "review_status": status,
        "adjudication_status": "adjudicated" if action == "adjudicate" else "needs_adjudication" if disputed else "not_required",
        "reviewer": reviewer, "review_timestamp": now, "review_notes": notes,
        "reviews": [*example.reviews, review],
    })


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 8)


def classification_metrics(expected: list[RoutingTier], selected: list[RoutingTier], confidences: list[float]) -> dict:
    if not (len(expected) == len(selected) == len(confidences)):
        raise ValueError("metric inputs must have equal lengths")
    total = len(expected)
    matrix = [[0] * 3 for _ in TIERS]
    for wanted, got in zip(expected, selected, strict=True):
        matrix[TIERS.index(wanted)][TIERS.index(got)] += 1
    scores = []
    for i in range(3):
        tp, predicted, actual = matrix[i][i], sum(row[i] for row in matrix), sum(matrix[i])
        precision, recall = (tp / predicted if predicted else 0), (tp / actual if actual else 0)
        scores.append((precision, recall, 2 * precision * recall / (precision + recall) if precision + recall else 0))
    correct = [wanted == got for wanted, got in zip(expected, selected, strict=True)]
    rate = lambda count: round(count / total, 4) if total else None
    buckets, ece = [], 0.0
    for i in range(5):
        members = [j for j, value in enumerate(confidences) if i / 5 <= value < (i + 1) / 5 or i == 4 and value == 1]
        average = statistics.mean(confidences[j] for j in members) if members else None
        accuracy = statistics.mean(correct[j] for j in members) if members else None
        if members:
            ece += len(members) / total * abs(accuracy - average)
        buckets.append({"minimum": i / 5, "maximum": (i + 1) / 5, "count": len(members),
                        "average_confidence": round(average, 4) if average is not None else None,
                        "accuracy": round(accuracy, 4) if accuracy is not None else None})
    pairs = list(zip(expected, selected, strict=True))
    return {
        "accuracy": rate(sum(correct)), "macro_precision": round(statistics.mean(x[0] for x in scores), 4) if total else None,
        "macro_recall": round(statistics.mean(x[1] for x in scores), 4) if total else None,
        "macro_f1": round(statistics.mean(x[2] for x in scores), 4) if total else None,
        "confusion_matrix": matrix,
        "under_routing_rate": rate(sum(TIERS.index(got) < TIERS.index(want) for want, got in pairs)),
        "over_routing_rate": rate(sum(TIERS.index(got) > TIERS.index(want) for want, got in pairs)),
        "unnecessary_expensive_routing_rate": rate(sum(want != RoutingTier.ADVANCED and got == RoutingTier.ADVANCED for want, got in pairs)),
        "basic_to_advanced_rate": rate(sum(want == RoutingTier.BASIC and got == RoutingTier.ADVANCED for want, got in pairs)),
        "advanced_to_basic_rate": rate(sum(want == RoutingTier.ADVANCED and got == RoutingTier.BASIC for want, got in pairs)),
        "confidence_distribution": buckets,
        "correctness_brier_score": round(statistics.mean((value - correct[i]) ** 2 for i, value in enumerate(confidences)), 4) if total else None,
        "expected_calibration_error": round(ece, 4) if total else None,
    }


def _dataset_metadata(rows: list[RoutingExample]) -> dict:
    reviews, sources, splits = Counter(row.review_status for row in rows), Counter(row.source for row in rows), Counter(row.dataset_split for row in rows)
    reviewed = sum(reviews[key] for key in REVIEWED)
    return {
        "version": sorted({row.dataset_version for row in rows}), "split_version": "family-aware-v1", "split_seed": 42,
        "total": len(rows), "human_reviewed": reviewed, "human_adjudicated": reviews["human_adjudicated"],
        "synthetic": sources["synthetic"], "machine_labeled": sources["machine_labeled"],
        "production_regressions": sources["production_regression"], "group_count": len({row.prompt_family for row in rows}),
        "split_sizes": {name: splits[name] for name in ("train", "validation", "test")},
        "group_leakage": False,
        "evidence_status": "reviewed" if reviewed == len(rows) and rows else "validation_incomplete",
    }


def benchmark(path: Path = DATASET_PATH) -> dict:
    """Evaluate stored, human-reviewed test predictions; never makes paid calls."""
    from backend.utils.yaml_config import load_routing_config

    rows = load_dataset(path)
    unavailable = [{"strategy": name, "status": "unavailable_no_reviewed_predictions"} for name in (
        "always_basic", "always_standard", "always_advanced", "heuristic_historical",
    )]
    local_path = ROOT / "artifacts" / "local_router" / "evaluation.json"
    local = json.loads(local_path.read_text()) if local_path.exists() else {
        "strategy": "local_semantic", "status": "unavailable_artifact_not_evaluated",
    }
    llm_path = ROOT / "artifacts" / "local_router" / "llm_evaluation.json"
    llm = json.loads(llm_path.read_text()) if llm_path.exists() else {
        "strategy": "llm_fallback", "status": "unavailable_not_evaluated",
    }
    config = load_routing_config()
    return {
        "benchmark_version": "routing-benchmark-v2.1", "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": _dataset_metadata(rows), "routing_policy_version": config["policy_version"],
        "production_policy": config.get("router", {}).get("production_policy", "unknown"),
        "classifier_model": config["classifier"]["model"], "router_version": "local-router-v1",
        "calibration_model": None, "calibration_status": "unavailable_insufficient_human_reviewed_validation_data",
        "evaluation_parameters": {"test_used_for_tuning": False, "paid_calls": llm_path.exists()},
        "strategies": [*unavailable, llm, local],
        "historical_synthetic_benchmark": {"reported_accuracy": 1.0, "generalization_valid": False,
            "label": "Historical synthetic benchmark — invalid for production-quality generalization claims."},
    }


def run_regressions(classifier=None, path: Path = DATASET_PATH) -> dict:
    """Run critical sanity prompts independently; callers opt into paid LLM calls."""
    from backend.services.classifier_service import ClassifierService
    from backend.services.routing_engine import RoutingEngine
    from backend.utils.config import get_settings

    classifier = classifier or ClassifierService(get_settings())
    engine = RoutingEngine()
    results = []
    for row in (item for item in load_dataset(path) if item.critical):
        outcome = classifier.classify(row.prompt)
        selected = engine.select(outcome.decision).tier
        results.append({
            "prompt_id": row.prompt_id, "prompt": row.prompt,
            "expected_tier": row.expected_tier.value, "predicted_tier": selected.value,
            "raw_confidence": outcome.decision.confidence,
            "calibrated_confidence": outcome.calibrated_confidence,
            "classifier_model": outcome.classifier_model, "fallback_used": outcome.fallback_used,
            "structured_classifier_output": not outcome.fallback_used,
            "passed": selected == row.expected_tier,
        })
    return {
        "passed": bool(results) and all(item["passed"] for item in results),
        "structured_output_passed": bool(results) and all(item["structured_classifier_output"] for item in results),
        "results": results,
    }


def release_gate(report: dict, regressions: dict | None = None, *, target_state: str = "PRODUCTION", minimum_reviewed: int = 1000) -> dict:
    """Pure, deterministic promotion decision over persisted benchmark evidence."""
    valid_states = {"EXPERIMENTAL", "VALIDATION", "PRODUCTION-CANDIDATE", "PRODUCTION"}
    if target_state not in valid_states:
        raise ValueError(f"Invalid release state: {target_state}")
    dataset = report.get("dataset", {})
    checks = {
        "benchmark_metadata": all(report.get(key) is not None for key in ("benchmark_version", "dataset", "router_version", "routing_policy_version")),
        "group_leakage": dataset.get("group_leakage") is False,
        "test_not_used_for_tuning": report.get("evaluation_parameters", {}).get("test_used_for_tuning") is False,
        "human_reviewed_evidence": dataset.get("human_reviewed", 0) >= minimum_reviewed,
        "confidence_calibration": report.get("calibration_status") == "validated",
        "canonical_regression": bool(regressions and regressions.get("passed")),
        "structured_classifier_output": bool(regressions and regressions.get("structured_output_passed")),
        "quality_threshold": report.get("quality_threshold_passed") is True,
        "cost_ceiling": report.get("cost_ceiling_passed") is True,
        "under_routing_threshold": report.get("under_routing_threshold_passed") is True,
    }
    if target_state in {"PRODUCTION-CANDIDATE", "PRODUCTION"}:
        required = checks
    elif target_state == "VALIDATION":
        required = {key: checks[key] for key in ("benchmark_metadata", "group_leakage", "test_not_used_for_tuning", "canonical_regression", "structured_classifier_output")}
    else:
        required = {key: checks[key] for key in ("benchmark_metadata", "group_leakage", "test_not_used_for_tuning")}
    return {"target_state": target_state, "allowed": all(required.values()), "checks": checks,
            "production_policy_frozen": report.get("production_policy") == "frozen", "current_state": "VALIDATION"}
