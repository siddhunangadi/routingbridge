import json

import numpy as np
import pytest

from backend.schemas.routing_decision import RoutingTier
from backend.services.local_semantic_router import (
    ArtifactLoadError,
    EmbeddingError,
    EmbeddingService,
    LocalSemanticRouter,
    load_artifact,
)


class _Encoder:
    def __init__(self, vector):
        self.vector = vector
        self.calls = 0

    def encode(self, _text, **_kwargs):
        self.calls += 1
        return np.asarray([self.vector] * len(_text))


class _Classifier:
    classes_ = np.array(["BASIC", "STANDARD", "ADVANCED"])

    def __init__(self, probabilities):
        self.probabilities = probabilities

    def predict_proba(self, _embedding):
        return np.array([self.probabilities])


def _router(probabilities=(0.08, 0.75, 0.17)):
    return LocalSemanticRouter(
        embedding_service=EmbeddingService(loader=lambda: _Encoder(np.ones(384, dtype=np.float32))),
        classifier=_Classifier(probabilities),
        metadata={"artifact_version": "test-v1", "embedding_dimension": 384},
    )


def test_embedding_is_finite_and_has_the_loaded_dimension():
    embedding = EmbeddingService(loader=lambda: _Encoder(np.ones(384, dtype=np.float32))).embed("hello")

    assert embedding.shape == (384,)
    assert np.isfinite(embedding).all()


def test_highest_probability_selects_standard_and_raw_confidence():
    result = _router().classify("summarize the report")

    assert result.routing_tier is RoutingTier.STANDARD
    assert result.raw_confidence == pytest.approx(0.75)
    assert result.p_basic == pytest.approx(0.08)
    assert result.p_standard == pytest.approx(0.75)
    assert result.p_advanced == pytest.approx(0.17)
    assert result.classifier_source == "local_semantic"


@pytest.mark.parametrize(("probabilities", "tier"), [
    ((0.8, 0.1, 0.1), RoutingTier.BASIC),
    ((0.1, 0.8, 0.1), RoutingTier.STANDARD),
    ((0.1, 0.1, 0.8), RoutingTier.ADVANCED),
])
def test_highest_probability_selects_each_tier(probabilities, tier):
    assert _router(probabilities).classify("prompt").routing_tier is tier


def test_probabilities_must_sum_to_one():
    with pytest.raises(EmbeddingError, match="sum to 1"):
        _router((0.2, 0.2, 0.2)).classify("prompt")


def test_probabilities_must_be_between_zero_and_one():
    with pytest.raises(EmbeddingError, match=r"within \[0, 1\]"):
        _router((-0.1, 0.6, 0.5)).classify("prompt")


@pytest.mark.parametrize("vector", [np.full(384, np.nan), np.full(384, np.inf), np.ones(383)])
def test_invalid_embedding_fails_clearly(vector):
    service = EmbeddingService(loader=lambda: _Encoder(vector))

    with pytest.raises(EmbeddingError):
        service.embed("prompt")


def test_embedding_model_is_loaded_once():
    encoder = _Encoder(np.ones(384))
    service = EmbeddingService(loader=lambda: encoder)

    service.embed("first")
    service.embed("second")

    assert encoder.calls == 2


def test_missing_or_corrupt_artifact_fails_clearly(tmp_path):
    with pytest.raises(ArtifactLoadError, match="missing"):
        load_artifact(tmp_path)
    (tmp_path / "classifier.joblib").write_text("not a joblib")
    (tmp_path / "metadata.json").write_text("{}")
    with pytest.raises(ArtifactLoadError, match="could not load"):
        load_artifact(tmp_path)


def test_artifact_metadata_contains_required_fields(tmp_path):
    metadata = {
        "dataset_version": "v2", "split_version": "v1", "seed": 42,
        "embedding_model": "BAAI/bge-small-en-v1.5", "embedding_dimension": 384,
        "class_labels": ["BASIC", "STANDARD", "ADVANCED"], "training_timestamp": "2026-08-24T00:00:00+00:00",
        "package_versions": {}, "training_row_count": 10, "provenance_summary": {}, "artifact_sha256": "abc",
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    assert json.loads((tmp_path / "metadata.json").read_text())["artifact_sha256"] == "abc"


def test_artifact_with_incomplete_metadata_is_rejected(tmp_path):
    import joblib

    joblib.dump(_Classifier((0.8, 0.1, 0.1)), tmp_path / "classifier.joblib")
    (tmp_path / "metadata.json").write_text("{}")

    with pytest.raises(ArtifactLoadError, match="metadata missing fields"):
        load_artifact(tmp_path)
