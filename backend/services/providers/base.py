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
    """Minimal interface: given a model name and a prompt, return text + token counts.

    `response_format="json_object"` requests structured JSON output from the
    model itself (rather than leaving JSON-vs-prose entirely up to prompt
    wording) — used by the classifier and quality verifier, which must parse
    the response as JSON. Regular chat answers pass no response_format.
    """

    @abstractmethod
    def generate(
        self, prompt: str, model: str, max_tokens: int = 1024, response_format: str | None = None
    ) -> ProviderResponse:
        raise NotImplementedError
