"""Word-count-based fallback routing decision.

This is intentionally the exception path, not the primary classifier. It
exists so that a Gemini outage or a malformed JSON response degrades the
system to "still works, slightly less accurately" instead of "500 error."
Reuses the same word-count thresholds from Settings that were originally
meant as the naive first-draft classifier — now repurposed as the safety net.
"""

from backend.schemas.routing_decision import ReasoningLevel, RoutingDecision, RoutingTier
from backend.utils.config import Settings


def classify_heuristically(prompt: str, settings: Settings) -> RoutingDecision:
    """Decide a routing tier by word count alone. Confidence is fixed and low
    by design — it signals to downstream consumers that this wasn't a real
    judgment call, just a safety-net guess.
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
        confidence=0.5,
        reason=f"Fallback heuristic: {word_count} words (LLM classifier unavailable)",
    )
