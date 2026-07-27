"""Word-count-based fallback routing decision.

This is intentionally the exception path, not the primary classifier. It
exists so that a classifier outage or a malformed JSON response degrades
the system to "still works, slightly less accurately" instead of "500
error." Reuses the same word-count thresholds from Settings that were
originally meant as the naive first-draft classifier — now repurposed as
the safety net.

Confidence review (engineering hardening pass): this used to hardcode
confidence=0.5, which sits *below* routing.yaml's default
`confidence_thresholds.low` (0.6). Since routing_engine.select() escalates
any decision whose confidence is under `low` by one tier, every single
fallback silently got escalated past the tier the word count itself just
picked — e.g. a 5-word prompt lands on BASIC by word count, then gets
bumped to STANDARD anyway, purely because 0.5 < 0.6. That interaction
wasn't documented anywhere and doesn't match the stated intent ("signals
this wasn't a real judgment call") — it's a bug, not a deliberate
double-degrade. Fixed by deriving the fallback's confidence from the
configured `low` threshold instead of a hardcoded number: just above it,
so the word-count tier is trusted and not auto-escalated, but still capped
below `high` so downstream consumers can still tell a fallback decision
apart from a genuine high-confidence classifier verdict.
"""

from backend.schemas.routing_decision import ReasoningLevel, RoutingDecision, RoutingTier
from backend.utils.config import Settings
from backend.utils.yaml_config import load_routing_config

# How far above confidence_thresholds.low to sit: enough to clear the
# escalation check with room for float rounding, without approaching
# `high` and looking like a genuine high-confidence classification.
_CONFIDENCE_MARGIN_ABOVE_LOW = 0.05


def _fallback_confidence() -> float:
    thresholds = load_routing_config()["confidence_thresholds"]
    low, high = thresholds["low"], thresholds["high"]
    return round(min(low + _CONFIDENCE_MARGIN_ABOVE_LOW, high - 0.01), 4)


def classify_heuristically(prompt: str, settings: Settings) -> RoutingDecision:
    """Decide a routing tier by word count alone. Confidence is deliberately
    just above the escalation threshold: high enough that the tier this
    function just picked isn't immediately overridden, but still visibly
    lower than a real classifier verdict — see module docstring.
    """
    word_count = len(prompt.split())

    if word_count <= settings.easy_max_words:
        tier, reasoning_level = RoutingTier.BASIC, ReasoningLevel.LOW
    elif word_count <= settings.medium_max_words:
        tier, reasoning_level = RoutingTier.STANDARD, ReasoningLevel.MEDIUM
    else:
        tier, reasoning_level = RoutingTier.ADVANCED, ReasoningLevel.HIGH

    return RoutingDecision(
        routing_tier=tier,
        task_type="Unknown",
        reasoning_level=reasoning_level,
        confidence=_fallback_confidence(),
        reason=f"Fallback heuristic: {word_count} words (LLM classifier unavailable)",
    )
