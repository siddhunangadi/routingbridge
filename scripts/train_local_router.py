"""Train the BGE + logistic-regression router from TRAIN rows only."""

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import joblib
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.local_semantic_router import EMBEDDING_DIMENSION, MODEL_ID, EmbeddingService
from backend.services.routing_evaluation import DATASET_PATH, RoutingExample, load_dataset, validate_group_splits

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "local_router"


def _fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def train_router(rows: list[RoutingExample], embeddings: EmbeddingService, output_dir: Path) -> dict:
    validate_group_splits(rows)
    train_rows = [row for row in rows if row.dataset_split == "train"]
    if set(row.expected_tier.value for row in train_rows) != {"BASIC", "STANDARD", "ADVANCED"}:
        raise ValueError("TRAIN split must contain BASIC, STANDARD, and ADVANCED rows")

    started = perf_counter()
    vectors = embeddings.embed_many([row.prompt for row in train_rows])
    embedding_seconds = perf_counter() - started
    classifier = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs", random_state=42)
    classifier.fit(vectors, [row.expected_tier.value for row in train_rows])

    output_dir.mkdir(parents=True, exist_ok=True)
    classifier_path = output_dir / "classifier.joblib"
    joblib.dump(classifier, classifier_path)
    metadata = {
        "artifact_version": "local-router-v1",
        "dataset_version": sorted({row.dataset_version for row in rows}),
        "dataset_sha256": _fingerprint([row.model_dump(mode="json") for row in rows]),
        "split_version": "family-aware-v1",
        "split_sha256": _fingerprint([(row.prompt_id, row.prompt_family, row.dataset_split) for row in rows]),
        "seed": 42,
        "embedding_model": MODEL_ID,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "embeddings_normalized": True,
        "classifier": "LogisticRegression(C=1.0, solver=lbfgs, max_iter=1000)",
        "class_labels": classifier.classes_.tolist(),
        "training_timestamp": datetime.now(timezone.utc).isoformat(),
        "training_row_count": len(train_rows),
        "split_counts": dict(Counter(row.dataset_split for row in rows)),
        "training_class_counts": dict(Counter(row.expected_tier.value for row in train_rows)),
        "provenance_summary": dict(Counter(row.provenance for row in rows)),
        "human_reviewed_count": sum(row.review_status in {"human_reviewed", "human_adjudicated"} for row in rows),
        "package_versions": {
            "python": platform.python_version(), "numpy": version("numpy"),
            "scikit-learn": version("scikit-learn"), "torch": version("torch"),
            "transformers": version("transformers"),
            "sentence-transformers": version("sentence-transformers"),
        },
        "embedding_training_seconds": round(embedding_seconds, 3),
        "calibration_status": "unavailable_insufficient_human_reviewed_validation_data",
        "artifact_sha256": hashlib.sha256(classifier_path.read_bytes()).hexdigest(),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--output", type=Path, default=ARTIFACT_DIR)
    args = parser.parse_args()
    print(json.dumps(train_router(load_dataset(args.dataset), EmbeddingService(), args.output), indent=2))
