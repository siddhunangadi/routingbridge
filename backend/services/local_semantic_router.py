"""Local BGE embedding plus persisted logistic-regression routing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable

import joblib
import numpy as np

from backend.schemas.routing_decision import RoutingTier

MODEL_ID = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSION = 384


class EmbeddingError(RuntimeError):
    pass


class ArtifactLoadError(RuntimeError):
    pass


@dataclass
class LocalRoutingDiagnostic:
    routing_tier: RoutingTier
    p_basic: float
    p_standard: float
    p_advanced: float
    raw_confidence: float
    embedding_dimension: int
    embedding_valid: bool
    classifier_artifact_version: str
    classifier_source: str = "local_semantic"
    embedding_latency_ms: float = 0.0
    classifier_latency_ms: float = 0.0


class EmbeddingService:
    def __init__(self, cache_dir: str | Path = "artifacts/bge", loader: Callable[[], object] | None = None):
        self.cache_dir = Path(cache_dir)
        self._loader = loader or self._load_model
        self._model = None

    def _load_model(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingError("sentence-transformers is not installed") from exc
        return SentenceTransformer(
            MODEL_ID, cache_folder=str(self.cache_dir), device="cpu", local_files_only=True,
        )

    def embed(self, text: str) -> np.ndarray:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            try:
                self._model = self._loader()
            except Exception as exc:
                raise EmbeddingError(f"could not load embedding model: {exc}") from exc
        try:
            vectors = np.asarray(
                self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False), dtype=np.float32,
            )
        except Exception as exc:
            raise EmbeddingError(f"could not create embedding: {exc}") from exc
        expected_shape = (len(texts), EMBEDDING_DIMENSION)
        if vectors.shape != expected_shape or not np.isfinite(vectors).all():
            raise EmbeddingError(f"invalid embedding shape or values: {vectors.shape}")
        return vectors


def load_artifact(directory: str | Path) -> tuple[object, dict]:
    directory = Path(directory)
    classifier_path, metadata_path = directory / "classifier.joblib", directory / "metadata.json"
    if not classifier_path.exists() or not metadata_path.exists():
        raise ArtifactLoadError(f"classifier artifact is missing from {directory}")
    try:
        classifier = joblib.load(classifier_path)
        metadata = json.loads(metadata_path.read_text())
    except Exception as exc:
        raise ArtifactLoadError(f"classifier artifact could not load: {exc}") from exc
    required = {
        "artifact_version", "dataset_version", "dataset_sha256", "split_version", "split_sha256",
        "seed", "embedding_model", "embedding_dimension", "class_labels", "training_timestamp",
        "training_row_count", "provenance_summary", "artifact_sha256",
    }
    missing = sorted(required - metadata.keys())
    if missing:
        raise ArtifactLoadError(f"classifier metadata missing fields: {', '.join(missing)}")
    if metadata.get("embedding_dimension") != EMBEDDING_DIMENSION:
        raise ArtifactLoadError("classifier artifact has an incompatible embedding dimension")
    if metadata.get("embedding_model") != MODEL_ID or set(metadata.get("class_labels", [])) != {tier.value for tier in RoutingTier}:
        raise ArtifactLoadError("classifier artifact has incompatible model or class labels")
    checksum = hashlib.sha256(classifier_path.read_bytes()).hexdigest()
    if metadata.get("artifact_sha256") != checksum:
        raise ArtifactLoadError("classifier artifact checksum does not match metadata")
    return classifier, metadata


class LocalSemanticRouter:
    def __init__(self, embedding_service: EmbeddingService, classifier: object, metadata: dict):
        self.embedding_service = embedding_service
        self.classifier = classifier
        self.metadata = metadata

    @classmethod
    def from_artifact(cls, artifact_dir: str | Path, cache_dir: str | Path = "artifacts/bge"):
        classifier, metadata = load_artifact(artifact_dir)
        return cls(EmbeddingService(cache_dir), classifier, metadata)

    def classify(self, prompt: str) -> LocalRoutingDiagnostic:
        started = perf_counter()
        embedding = self.embedding_service.embed(prompt)
        embedding_latency_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        try:
            probabilities = np.asarray(self.classifier.predict_proba([embedding])[0], dtype=float)
            labels = [RoutingTier(value) for value in self.classifier.classes_]
        except Exception as exc:
            raise EmbeddingError(f"classifier inference failed: {exc}") from exc
        if (
            len(probabilities) != 3 or not np.isfinite(probabilities).all()
            or not ((0 <= probabilities) & (probabilities <= 1)).all()
            or not np.isclose(probabilities.sum(), 1.0)
        ):
            raise EmbeddingError("classifier probabilities must be within [0, 1] and sum to 1")
        values = {label: float(probability) for label, probability in zip(labels, probabilities)}
        tier = max(values, key=values.get)
        return LocalRoutingDiagnostic(
            routing_tier=tier, p_basic=values[RoutingTier.BASIC], p_standard=values[RoutingTier.STANDARD],
            p_advanced=values[RoutingTier.ADVANCED], raw_confidence=values[tier],
            embedding_dimension=len(embedding), embedding_valid=True,
            classifier_artifact_version=self.metadata.get("artifact_version", "unknown"),
            embedding_latency_ms=round(embedding_latency_ms, 2),
            classifier_latency_ms=round((perf_counter() - started) * 1000, 2),
        )
