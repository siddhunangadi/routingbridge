"""Google Gemini provider — native SDK, used for both the classifier and
the "easy" tier since we already hold a Google API key."""

import google.generativeai as genai

from backend.services.providers.base import LLMProvider, ProviderResponse


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)

    def generate(
        self, prompt: str, model: str, max_tokens: int = 1024, response_format: str | None = None
    ) -> ProviderResponse:
        client = genai.GenerativeModel(model)
        generation_config = genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if response_format == "json_object" else None,
        )
        response = client.generate_content(prompt, generation_config=generation_config)
        usage = response.usage_metadata
        return ProviderResponse(
            text=response.text,
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
        )
