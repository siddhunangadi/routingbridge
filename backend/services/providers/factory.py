"""Provider factory: turns a provider name from routing.yaml into a live
LLMProvider instance. A plain function + dict is enough here — a full
Factory-pattern class would be ceremony for two providers.
"""

from backend.services.providers.base import LLMProvider
from backend.services.providers.gemini_provider import GeminiProvider
from backend.services.providers.openrouter_provider import OpenRouterProvider
from backend.utils.config import Settings


def get_provider(name: str, settings: Settings) -> LLMProvider:
    if name == "google":
        return GeminiProvider(settings.google_api_key)
    if name == "openrouter":
        return OpenRouterProvider(settings.openrouter_api_key)
    raise ValueError(f"Unknown provider '{name}'. Expected 'google' or 'openrouter'.")
