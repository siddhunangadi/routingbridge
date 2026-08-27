"""Local semantic routing with a validated Mistral fallback."""

import logging
import math
import time
from functools import lru_cache

from backend.schemas.routing_decision import ReasoningLevel, RoutingDecision, RoutingDecisionOutcome, RoutingTier
from backend.services.cost_estimator import estimate_cost
from backend.services.local_semantic_router import MODEL_ID, LocalSemanticRouter
from backend.services.providers.factory import get_provider
from backend.utils.config import Settings, get_settings
from backend.utils.yaml_config import load_routing_config

logger = logging.getLogger(__name__)


class RoutingClassifierError(RuntimeError):
    pass


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    return stripped.strip()


def _build_classifier_prompt(user_prompt: str) -> str:
    return (
        "Classify the prompt for model routing; do not answer it. "
        "Confidence is your uncalibrated self-assessment, not a probability of correctness.\n"
        "Return JSON only: "
        '{"routing_tier":"BASIC|STANDARD|ADVANCED","task_type":"short label",'
        '"reasoning_level":"Low|Medium|High","confidence":0.0,"reason":"max 20 words"}\n'
        f'Prompt: """{user_prompt}"""'
    )


class ClassifierService:
    def __init__(self, settings: Settings, *, local_router=None, provider=None):
        self._settings = settings
        config = load_routing_config()["classifier"]
        self._provider_name = config["provider"]
        self._model_name = config["model"]
        self._max_output_tokens = config["max_output_tokens"]
        self._provider = provider
        self._local_router = local_router
        self._local_initialized = local_router is not None
        self._local_error = None
        if self._provider is None and getattr(settings, f"{self._provider_name}_api_key", ""):
            self._provider = get_provider(self._provider_name, settings)

    def _get_local_router(self):
        if not self._local_initialized:
            self._local_initialized = True
            try:
                self._local_router = LocalSemanticRouter.from_artifact(
                    self._settings.local_router_artifact_dir, self._settings.bge_cache_dir,
                )
            except Exception as exc:
                self._local_error = exc
        if self._local_router is None:
            raise RuntimeError(f"local router unavailable: {self._local_error}")
        return self._local_router

    def _classify_with_llm(self, prompt: str, started: float, fallback_reason: str | None, local_result=None) -> RoutingDecisionOutcome:
        if self._provider is None:
            raise RuntimeError(f"{self._provider_name}_api_key not configured")
        response = self._provider.generate(
            _build_classifier_prompt(prompt), self._model_name,
            self._max_output_tokens, response_format="json_object",
        )
        decision = RoutingDecision.model_validate_json(strip_json_fence(response.text))
        return RoutingDecisionOutcome(
            decision=decision, classifier_model=self._model_name,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            input_tokens=response.input_tokens, output_tokens=response.output_tokens,
            cost=estimate_cost(self._model_name, response.input_tokens, response.output_tokens),
            fallback_used=fallback_reason is not None, classifier_source="llm_fallback",
            fallback_reason=fallback_reason,
            p_basic=local_result.p_basic if local_result else None,
            p_standard=local_result.p_standard if local_result else None,
            p_advanced=local_result.p_advanced if local_result else None,
        )

    def classify(self, prompt: str) -> RoutingDecisionOutcome:
        started = time.perf_counter()
        local_error = None
        local_result = None
        if self._settings.router_mode in {"local", "validation"}:
            try:
                local_result = self._get_local_router().classify(prompt)
                if not math.isfinite(local_result.raw_confidence) or not 0 <= local_result.raw_confidence <= 1:
                    raise ValueError("local router returned unusable confidence")
                if local_result.raw_confidence < self._settings.local_router_fallback_threshold:
                    raise ValueError(
                        f"raw confidence {local_result.raw_confidence:.4f} below experimental threshold "
                        f"{self._settings.local_router_fallback_threshold:.4f}"
                    )
                reasoning = {
                    RoutingTier.BASIC: ReasoningLevel.LOW,
                    RoutingTier.STANDARD: ReasoningLevel.MEDIUM,
                    RoutingTier.ADVANCED: ReasoningLevel.HIGH,
                }[local_result.routing_tier]
                return RoutingDecisionOutcome(
                    decision=RoutingDecision(
                        routing_tier=local_result.routing_tier, task_type="local_semantic",
                        reasoning_level=reasoning, confidence=local_result.raw_confidence,
                        reason="BGE embedding classified by local logistic regression",
                    ),
                    classifier_model=MODEL_ID, latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    input_tokens=0, output_tokens=0, cost=0.0, fallback_used=False,
                    classifier_source="local_semantic", p_basic=local_result.p_basic,
                    p_standard=local_result.p_standard, p_advanced=local_result.p_advanced,
                )
            except Exception as exc:
                local_error = str(exc)
                if local_result is not None:
                    probabilities = [local_result.p_basic, local_result.p_standard, local_result.p_advanced]
                    usable = all(math.isfinite(value) and 0 <= value <= 1 for value in probabilities)
                    if not usable or not math.isclose(sum(probabilities), 1.0):
                        local_result = None
                logger.warning("Local router failed; using Mistral fallback: %s", exc)

        try:
            return self._classify_with_llm(prompt, started, local_error, local_result)
        except Exception as exc:
            message = f"Mistral routing fallback failed: {exc}"
            if local_error is not None:
                message = f"Local router failed ({local_error}); {message}"
            raise RoutingClassifierError(message) from exc


@lru_cache
def get_classifier_service() -> ClassifierService:
    return ClassifierService(get_settings())
