"""Word-count-based fallback classifier.

This is intentionally the exception path, not the primary classifier. It
exists so that a Gemini outage or a malformed JSON response degrades the
system to "still works, slightly less accurately" instead of "500 error."
Reuses the same word-count thresholds from Settings that were originally
meant as the naive first-draft classifier — now repurposed as the safety net.
"""

from backend.schemas.classification import ClassificationResult, Complexity
from backend.utils.config import Settings


def classify_heuristically(prompt: str, settings: Settings) -> ClassificationResult:
    """Classify by word count alone. Confidence is fixed and low by design —
    it signals to downstream consumers that this wasn't a real judgment call.
    """
    word_count = len(prompt.split())

    if word_count <= settings.easy_max_words:
        complexity = Complexity.EASY
    elif word_count <= settings.medium_max_words:
        complexity = Complexity.MEDIUM
    else:
        complexity = Complexity.HARD

    return ClassificationResult(
        complexity=complexity,
        confidence=0.5,
        reason=f"Fallback heuristic: {word_count} words (LLM classifier unavailable)",
    )
