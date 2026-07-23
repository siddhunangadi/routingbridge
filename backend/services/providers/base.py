"""Provider abstraction: the routing engine talks to this interface only,
never to a specific SDK.

Two implementations exist — GeminiProvider (native Google SDK) and
OpenRouterProvider (single REST gateway to Mistral/DeepSeek/Qwen/Llama/etc).
Adding a third provider later means writing one class, not touching the
routing engine or the chat endpoint.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class ProviderResponse(BaseModel):
    """Normalized shape every provider must return, regardless of SDK."""

    text: str
    input_tokens: int
    output_tokens: int


class LLMProvider(ABC):
    """Minimal interface: given a model name and a prompt, return text + token counts."""

    @abstractmethod
    def generate(self, prompt: str, model: str, max_tokens: int = 1024) -> ProviderResponse:
        raise NotImplementedError
