"""Quality verification: an LLM judge grading whether the cheap tier's
answer was actually good enough.

Reuses the same cheap classifier model (a Mistral model via OpenRouter,
see routing.yaml) rather than introducing a second model just for judging —
the judge's job is small (read a Q&A pair, say pass/fail) and doesn't need
a bigger model.

Only called for BASIC/STANDARD tier answers (see chat.py) — there's no
value judging the ADVANCED tier against itself, since routing already
gave that prompt the most capable model available.

Verification failure (bad API key, malformed JSON, rate limit) returns
None rather than raising — a broken judge should never block the user
from getting their actual answer.
"""

import json
import logging
from functools import lru_cache

from backend.schemas.quality import QualityVerdict
from backend.services.providers.factory import get_provider
from backend.utils.config import Settings, get_settings
from backend.utils.yaml_config import load_routing_config

logger = logging.getLogger(__name__)


def _build_verdict_prompt(prompt: str, response: str) -> str:
    return (
        "You are grading whether an AI response adequately and correctly "
        "answers the user's prompt. Be strict but fair — minor style issues "
        "don't count as a failure, wrong or incomplete answers do.\n\n"
        "Respond with JSON only, matching exactly this shape:\n"
        '{"passed": true|false, "reason": "<short reason, max 20 words>"}\n\n'
        f'Prompt: """{prompt}"""\n\n'
        f'Response: """{response}"""'
    )


class QualityVerifier:
    def __init__(self, settings: Settings):
        routing_cfg = load_routing_config()["classifier"]
        provider_name: str = routing_cfg["provider"]
        self._model_name: str = routing_cfg["model"]

        api_key = getattr(settings, f"{provider_name}_api_key", "")
        self._client_ready = bool(api_key)
        if self._client_ready:
            self._provider = get_provider(provider_name, settings)

    def verify(self, prompt: str, response: str) -> QualityVerdict | None:
        if not self._client_ready:
            return None
        try:
            result = self._provider.generate(
                _build_verdict_prompt(prompt, response), self._model_name, 200
            )
            data = json.loads(result.text)
            return QualityVerdict.model_validate(data)
        except (Exception,) as exc:  # noqa: BLE001 - judge failure must never block the response
            logger.warning("Quality verification failed (%s); skipping", exc)
            return None


@lru_cache
def get_quality_verifier() -> QualityVerifier:
    """FastAPI dependency: one verifier instance per process, same pattern as get_settings()."""
    return QualityVerifier(get_settings())
