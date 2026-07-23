"""Routing engine: turns a classifier's RoutingDecision into a concrete
provider + model to call.

Deliberately knows nothing about "Gemini" or "DeepSeek" — it only knows
tiers (BASIC/STANDARD/ADVANCED) and reads routing.yaml to find out which
provider/model currently serves each tier. Swapping which model serves
ADVANCED is a one-line YAML edit; this file never changes.
"""

from functools import lru_cache

from backend.schemas.routing import RoutingResult
from backend.schemas.routing_decision import RoutingDecision, RoutingTier
from backend.utils.yaml_config import load_routing_config

_TIER_ORDER = [RoutingTier.BASIC, RoutingTier.STANDARD, RoutingTier.ADVANCED]


def _next_tier(tier: RoutingTier) -> RoutingTier | None:
    idx = _TIER_ORDER.index(tier)
    return _TIER_ORDER[idx + 1] if idx + 1 < len(_TIER_ORDER) else None


class RoutingEngine:
    def __init__(self):
        self._config = load_routing_config()

    def select(self, decision: RoutingDecision) -> RoutingResult:
        """Pick a provider/model for a routing decision, escalating one tier
        up if the classifier's confidence was too low to trust its own call.
        """
        tier = decision.routing_tier
        escalated = False

        thresholds = self._config["confidence_thresholds"]
        if thresholds["escalate_on_low_confidence"] and decision.confidence < thresholds["low"]:
            candidate = _next_tier(tier)
            if candidate is not None:
                tier = candidate
                escalated = True

        tier_config = self._config["tiers"][tier.value.lower()]
        reasons = list(tier_config["reasons"])
        if escalated:
            reasons.append(
                f"Escalated from {decision.routing_tier.value} due to low "
                f"classifier confidence ({decision.confidence:.2f})"
            )

        return RoutingResult(
            provider=tier_config["provider"],
            model=tier_config["model"],
            tier=tier,
            original_tier=decision.routing_tier,
            escalated=escalated,
            reasons=reasons,
        )


@lru_cache
def get_routing_engine() -> RoutingEngine:
    """FastAPI dependency: one engine instance per process, same pattern as get_settings()."""
    return RoutingEngine()
