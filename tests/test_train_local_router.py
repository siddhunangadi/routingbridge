import json

import numpy as np

from backend.schemas.routing_decision import ReasoningLevel, RoutingTier
from backend.services.local_semantic_router import load_artifact
from backend.services.routing_evaluation import RoutingExample
from scripts.train_local_router import train_router


class _Embeddings:
    def __init__(self):
        self.prompts = []

    def embed_many(self, prompts):
        self.prompts.extend(prompts)
        vectors = np.zeros((len(prompts), 384), dtype=np.float32)
        for index, prompt in enumerate(prompts):
            vectors[index, int(prompt.split("-")[0])] = 1
        return vectors


def _row(prompt_id, tier, split="train"):
    return RoutingExample(
        prompt_id=prompt_id, prompt=f"{list(RoutingTier).index(tier)}-{prompt_id}", expected_tier=tier,
        task_type="test", reasoning_level=ReasoningLevel.LOW, prompt_family=prompt_id,
        source="synthetic", provenance="AI_generated", review_status="pending_owner_review",
        adjudication_status="not_required", dataset_version="test-v1", dataset_split=split,
    )


def test_training_uses_train_split_only_and_writes_valid_artifact(tmp_path):
    rows = [
        *[_row(f"basic-{i}", RoutingTier.BASIC) for i in range(3)],
        *[_row(f"standard-{i}", RoutingTier.STANDARD) for i in range(3)],
        *[_row(f"advanced-{i}", RoutingTier.ADVANCED) for i in range(3)],
        _row("held-out", RoutingTier.ADVANCED, "test"),
    ]
    embeddings = _Embeddings()

    metadata = train_router(rows, embeddings, tmp_path)
    classifier, loaded_metadata = load_artifact(tmp_path)

    assert "2-held-out" not in embeddings.prompts
    assert metadata["training_row_count"] == 9
    assert loaded_metadata["class_labels"] == ["ADVANCED", "BASIC", "STANDARD"]
    assert classifier.predict([[1, *([0] * 383)]])[0] == "BASIC"
    assert json.loads((tmp_path / "metadata.json").read_text())["artifact_sha256"]
