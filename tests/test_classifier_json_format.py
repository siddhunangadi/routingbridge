"""Regression coverage for the production stabilization fix: the OpenRouter
classifier and quality verifier were silently dead in production because
Mistral wraps its JSON reply in a ```json markdown fence and
OpenRouterProvider never requested response_format="json_object" — every
real call failed to parse and fell back to the heuristic (see
docs/architecture.md's "Production stabilization notes"). These tests
pin down the fix at both layers: the provider must actually send
response_format when asked, and the parsing layer must survive a fence
even if a provider doesn't honor it.
"""

import httpx
import pytest

from backend.services.classifier_service import strip_json_fence
from backend.services.providers.openrouter_provider import OpenRouterProvider


def test_strip_json_fence_removes_fenced_markdown():
    fenced = '```json\n{"a": 1}\n```'
    assert strip_json_fence(fenced) == '{"a": 1}'


def test_strip_json_fence_passes_through_plain_json():
    plain = '{"a": 1}'
    assert strip_json_fence(plain) == plain


def test_openrouter_provider_requests_json_object_format(monkeypatch):
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    def fake_post(url, *, headers, json, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    provider = OpenRouterProvider(api_key="fake-key")
    provider.generate("prompt", "some-model", response_format="json_object")

    assert captured["json"]["response_format"] == {"type": "json_object"}


def test_openrouter_provider_omits_response_format_for_regular_chat(monkeypatch):
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": "a real chat answer"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    def fake_post(url, *, headers, json, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    provider = OpenRouterProvider(api_key="fake-key")
    provider.generate("prompt", "some-model")

    assert "response_format" not in captured["json"]
