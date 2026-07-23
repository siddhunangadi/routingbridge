"""OpenRouter provider — a single REST gateway giving access to Mistral,
DeepSeek, Qwen, Llama and other open-weight models via one OpenAI-compatible
API. This is why one class here covers every "standard"/"advanced" tier
model instead of writing a client per open-source provider.
"""

import httpx

from backend.services.providers.base import LLMProvider, ProviderResponse

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str):
        self._api_key = api_key

    def generate(self, prompt: str, model: str, max_tokens: int = 1024) -> ProviderResponse:
        response = httpx.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return ProviderResponse(
            text=text,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
