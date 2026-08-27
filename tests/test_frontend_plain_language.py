from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest


APP = Path(__file__).parents[1] / "frontend" / "streamlit_app.py"


class FakeResponse:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def fake_request(method, url, **kwargs):
    if url.endswith("/chat"):
        return FakeResponse(
            {
                "response": "Paris",
                "routing_tier": "BASIC",
                "original_tier": "BASIC",
                "escalated": False,
                "provider": "google",
                "model": "gemini-2.5-flash",
                "task_type": "local_semantic",
                "confidence": 0.8,
                "classifier_source": "local_semantic",
                "fallback_used": False,
                "total_cost": 0.00001,
                "model_cost": 0.00001,
                "classifier_cost": 0.0,
                "classifier_latency_ms": 20,
                "generation_latency_ms": 400,
                "total_latency_ms": 420,
                "classifier_model": "BAAI/bge-small-en-v1.5",
                "quality_passed": True,
                "quality_reason": "Correct answer.",
                "routing_reason": ["A quick factual question"],
            }
        )
    if url.endswith("/history"):
        return FakeResponse(
            [
                {
                    "timestamp": "2026-08-24T09:00:00Z",
                    "prompt": "What is the capital of France?",
                    "routing_tier": "BASIC",
                    "provider": "google",
                    "model": "gemini-2.5-flash",
                    "classifier_source": "local_semantic",
                    "total_cost": 0.00001,
                    "total_latency_ms": 420,
                    "fallback_used": False,
                }
            ]
        )
    if url.endswith("/analytics/benchmark"):
        return FakeResponse(
            {
                "dataset": {
                    "version": ["routing-dataset-v2"],
                    "total": 1051,
                    "group_count": 31,
                    "split_sizes": {"train": 735, "validation": 175, "test": 141},
                    "human_reviewed": 0,
                },
                "benchmark_version": "routing-benchmark-v2.1",
                "calibration_status": "unavailable",
                "strategies": [],
            }
        )
    if url.endswith("/stats"):
        return FakeResponse(
            {
                "total_requests": 1,
                "total_cost": 0.01,
                "estimated_savings": 0.02,
                "avg_latency_ms": 1200,
                "quality_pass_rate": 1.0,
                "quality_verified_count": 1,
                "requests_per_tier": {"BASIC": 1},
                "cost_per_model": {"gemini-2.5-flash": 0.01},
            }
        )
    if url.endswith("/models"):
        return FakeResponse(
            {
                "router_mode": "local",
                "primary_classifier": "local_semantic",
                "fallback_classifier": "llm_fallback",
                "local_fallback_threshold": 0.6,
                "local_confidence_status": "uncalibrated_experimental_signal",
                "classifier": {"model": "mistralai/mistral-small-3.2-24b-instruct"},
                "tiers": {
                    "basic": {
                        "provider": "google",
                        "model": "gemini-2.5-flash",
                        "max_output_tokens": 1024,
                        "input_per_million": 0.3,
                        "output_per_million": 2.5,
                        "reasons": ["Simple questions and quick answers"],
                    },
                    "standard": {
                        "provider": "openrouter",
                        "model": "mistralai/mistral-small-3.2-24b-instruct",
                        "max_output_tokens": 1536,
                        "input_per_million": 0.1,
                        "output_per_million": 0.3,
                        "reasons": ["Everyday explanations and summaries"],
                    },
                    "advanced": {
                        "provider": "openrouter",
                        "model": "deepseek/deepseek-r1",
                        "max_output_tokens": 4096,
                        "input_per_million": 0.55,
                        "output_per_million": 2.19,
                        "reasons": ["Complex planning and technical problems"],
                    },
                },
            }
        )
    raise AssertionError(f"Unexpected request: {method} {url}")


def test_analytics_hides_internal_evaluation(monkeypatch):
    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.syspath_prepend(str(APP.parent))
    app = AppTest.from_file(str(APP)).run()
    app.radio[0].set_value("Analytics").run()

    visible_text = " ".join(element.value for element in app.markdown)
    assert "Routing Evaluation" not in visible_text
    assert "reviewed-label validation" not in visible_text
    assert "routing-dataset-v2" not in visible_text
    assert "Total Requests" in visible_text


def test_chat_shows_decision_without_classifier_internals(monkeypatch):
    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.syspath_prepend(str(APP.parent))
    app = AppTest.from_file(str(APP)).run()
    app.text_area[0].set_value("What is the capital of France?")
    app.button[0].click().run()

    visible_text = " ".join(element.value for element in app.markdown)
    assert "Routing Tier" in visible_text
    assert "gemini-2.5-flash" in visible_text
    assert "Total Cost" in visible_text
    assert "Response Time" in visible_text
    assert "Raw Confidence" not in visible_text
    assert "Classifier Source" not in visible_text
    assert "Classifier Latency" not in visible_text


def test_history_keeps_only_visitor_friendly_columns(monkeypatch):
    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.syspath_prepend(str(APP.parent))
    app = AppTest.from_file(str(APP)).run()
    app.radio[0].set_value("History").run()

    assert list(app.dataframe[0].value.columns) == [
        "Time",
        "Prompt",
        "Tier",
        "Model",
        "Cost ($)",
        "Response Time (ms)",
    ]


def test_settings_shows_friendly_tiers_without_classifier_internals(monkeypatch):
    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.syspath_prepend(str(APP.parent))
    app = AppTest.from_file(str(APP)).run()
    app.radio[0].set_value("Settings").run()

    visible_text = " ".join(element.value for element in app.markdown)
    assert "config/routing.yaml" not in visible_text
    assert "Primary Classifier" not in visible_text
    assert "Raw Confidence" not in visible_text
    assert "Best for" in visible_text
    assert all(tier in visible_text for tier in ("BASIC", "STANDARD", "ADVANCED"))
