"""LLM-powered routing classifier.

Uses a small, cheap model (configured in routing.yaml, default a Mistral
model via OpenRouter) purely as a *router* — it never answers the user's
prompt, only decides which routing tier should handle it. This mirrors a
real production pattern: a cheap gating model in front of expensive ones.

Falls back to `heuristic_classifier` if the LLM call fails or returns
output that doesn't validate against `RoutingDecision`. The fallback
is the exception path, not the primary one — see `classify()`.
"""

import json
import logging
import time
from functools import lru_cache

from pydantic import ValidationError

from backend.schemas.routing_decision import RoutingDecision, RoutingDecisionOutcome
from backend.services.cost_estimator import estimate_cost
from backend.services.heuristic_classifier import classify_heuristically
from backend.services.providers.factory import get_provider
from backend.utils.config import Settings, get_settings
from backend.utils.yaml_config import load_routing_config

logger = logging.getLogger(__name__)


def strip_json_fence(text: str) -> str:
    """Defensive belt-and-suspenders: `response_format="json_object"` is what
    actually fixes structured output (verified against the real OpenRouter
    API — Mistral otherwise wraps its reply in a ```json fence and breaks
    json.loads() on every call), but this strips a fence anyway in case a
    future routing.yaml model swap doesn't honor response_format reliably.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
    return stripped.strip()


def _build_classifier_prompt(user_prompt: str) -> str:
    """Kept deliberately tiny: every extra token here is paid on every request."""
    return (
        "You are a routing classifier for an LLM system. Decide which routing "
        "tier the prompt below needs, and briefly describe it. Do not answer "
        "the prompt yourself.\n\n"
        "Respond with JSON only, matching exactly this shape:\n"
        '{"routing_tier": "BASIC"|"STANDARD"|"ADVANCED", '
        '"task_type": "<short label, e.g. Summarization, CodeGen, Q&A, Reasoning>", '
        '"reasoning_level": "Low"|"Medium"|"High", '
        '"confidence": <0-1 float>, '
        '"reason": "<short reason, max 20 words>"}\n\n'
        f'Prompt: """{user_prompt}"""'
    )


class ClassifierService:
    """Routes prompts to a cheap LLM for complexity classification."""

    def __init__(self, settings: Settings):
        self._settings = settings

        routing_cfg = load_routing_config()["classifier"]
        self._provider_name: str = routing_cfg["provider"]
        self._model_name: str = routing_cfg["model"]
        self._max_output_tokens: int = routing_cfg["max_output_tokens"]

        api_key = getattr(settings, f"{self._provider_name}_api_key", "")
        self._client_ready = bool(api_key)
        if self._client_ready:
            self._provider = get_provider(self._provider_name, settings)

    def classify(self, prompt: str) -> RoutingDecisionOutcome:
        """Make a routing decision for a prompt, falling back to heuristics on any LLM failure."""
        start = time.perf_counter()
        input_tokens = output_tokens = 0
        fallback_used = False

        try:
            if not self._client_ready:
                raise RuntimeError(f"{self._provider_name}_api_key not configured")
            decision, input_tokens, output_tokens = self._classify_with_llm(prompt)
        except (Exception,) as exc:  # noqa: BLE001 - any failure here must degrade, not crash
            logger.warning("Classifier LLM call failed (%s); using heuristic fallback", exc)
            decision = classify_heuristically(prompt, self._settings)
            fallback_used = True

        latency_ms = (time.perf_counter() - start) * 1000
        cost = 0.0 if fallback_used else estimate_cost(self._model_name, input_tokens, output_tokens)

        return RoutingDecisionOutcome(
            decision=decision,
            classifier_model=self._model_name if not fallback_used else "heuristic",
            latency_ms=round(latency_ms, 2),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            fallback_used=fallback_used,
        )

    def _classify_with_llm(self, prompt: str) -> tuple[RoutingDecision, int, int]:
        response = self._provider.generate(
            _build_classifier_prompt(prompt),
            self._model_name,
            self._max_output_tokens,
            response_format="json_object",
        )

        try:
            data = json.loads(strip_json_fence(response.text))
            decision = RoutingDecision.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"Classifier returned invalid structured output: {exc}") from exc

        return decision, response.input_tokens, response.output_tokens


@lru_cache
def get_classifier_service() -> ClassifierService:
    """FastAPI dependency: one classifier instance per process, same pattern as get_settings()."""
    return ClassifierService(get_settings())
