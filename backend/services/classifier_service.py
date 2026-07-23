"""LLM-powered routing classifier.

Uses a small, cheap model (configured in routing.yaml, default Gemini 2.5
Flash) purely as a *router* — it never answers the user's prompt, only
decides which routing tier should handle it. This mirrors a real production
pattern: a cheap gating model in front of expensive ones.

Falls back to `heuristic_classifier` if the LLM call fails or returns
output that doesn't validate against `RoutingDecision`. The fallback
is the exception path, not the primary one — see `classify()`.
"""

import json
import logging
import time

import google.generativeai as genai
from pydantic import ValidationError

from backend.schemas.routing_decision import RoutingDecision, RoutingDecisionOutcome
from backend.services.heuristic_classifier import classify_heuristically
from backend.utils.config import Settings
from backend.utils.yaml_config import load_pricing_config, load_routing_config

logger = logging.getLogger(__name__)


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
        self._model_name: str = routing_cfg["model"]
        self._max_output_tokens: int = routing_cfg["max_output_tokens"]

        pricing = load_pricing_config()["models"][self._model_name]
        self._input_price_per_million: float = pricing["input_per_million"]
        self._output_price_per_million: float = pricing["output_per_million"]

        self._client_ready = bool(settings.google_api_key)
        if self._client_ready:
            genai.configure(api_key=settings.google_api_key)

    def classify(self, prompt: str) -> RoutingDecisionOutcome:
        """Make a routing decision for a prompt, falling back to heuristics on any LLM failure."""
        start = time.perf_counter()
        input_tokens = output_tokens = 0
        fallback_used = False

        try:
            if not self._client_ready:
                raise RuntimeError("GOOGLE_API_KEY not configured")
            decision, input_tokens, output_tokens = self._classify_with_llm(prompt)
        except (Exception,) as exc:  # noqa: BLE001 - any failure here must degrade, not crash
            logger.warning("Classifier LLM call failed (%s); using heuristic fallback", exc)
            decision = classify_heuristically(prompt, self._settings)
            fallback_used = True

        latency_ms = (time.perf_counter() - start) * 1000
        cost = 0.0 if fallback_used else self._estimate_cost(input_tokens, output_tokens)

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
        model = genai.GenerativeModel(self._model_name)
        response = model.generate_content(
            _build_classifier_prompt(prompt),
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=self._max_output_tokens,
            ),
        )

        try:
            data = json.loads(response.text)
            decision = RoutingDecision.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"Classifier returned invalid structured output: {exc}") from exc

        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count if usage else 0
        output_tokens = usage.candidates_token_count if usage else 0
        return decision, input_tokens, output_tokens

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        input_cost = (input_tokens / 1_000_000) * self._input_price_per_million
        output_cost = (output_tokens / 1_000_000) * self._output_price_per_million
        return round(input_cost + output_cost, 8)
