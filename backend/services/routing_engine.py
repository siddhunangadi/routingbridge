"""Routing engine: turns a classifier's RoutingDecision into a concrete
provider + model to call.

Deliberately knows nothing about "Gemini" or "DeepSeek" — it only knows
tiers (BASIC/STANDARD/ADVANCED) and reads routing.yaml to find out which
provider/model currently serves each tier. Swapping which model serves
ADVANCED is a one-line YAML edit; this file never changes.
"""

from functools import lru_cache

from backend.schemas.routing import RoutingCandidate, RoutingResult
from backend.schemas.routing_decision import RoutingDecision, RoutingTier
from backend.utils.yaml_config import load_routing_config

class RoutingEngine:
    def __init__(self):
        self._config = load_routing_config()

    def select(self, decision: RoutingDecision) -> RoutingResult:
        """Deterministically map the classifier's final tier to configured models."""
        tier = decision.routing_tier

        tier_config = self._config["tiers"][tier.value.lower()]
        candidate_configs = tier_config.get("candidates") or [tier_config]
        minimum_quality = tier_config.get("minimum_quality", 0.0)
        eligible = [
            candidate
            for candidate in candidate_configs
            if candidate.get("healthy", True)
            and candidate.get("expected_quality", 1.0) >= minimum_quality
        ]
        if not eligible:
            eligible = [candidate_configs[0]]
        eligible.sort(key=lambda candidate: (candidate.get("expected_cost", 0.0), candidate.get("expected_latency_ms", 0)))
        candidates = [RoutingCandidate(**candidate) for candidate in eligible]
        selected = candidates[0]
        reasons = list(tier_config["reasons"])
        if len(candidates) > 1:
            reasons.append("Lowest-cost healthy candidate meeting the quality policy")
        return RoutingResult(
            provider=selected.provider,
            model=selected.model,
            max_output_tokens=selected.max_output_tokens,
            tier=tier,
            original_tier=decision.routing_tier,
            escalated=False,
            reasons=reasons,
            candidates=candidates,
        )


@lru_cache
def get_routing_engine() -> RoutingEngine:
    """FastAPI dependency: one engine instance per process, same pattern as get_settings()."""
    return RoutingEngine()
