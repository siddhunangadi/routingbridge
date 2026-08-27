"""POST /chat — the core request flow: classify, route, call the selected
model, estimate cost, persist, respond.

This function is intentionally a straight line, not a pipeline abstraction:
classify -> route -> generate -> cost -> save -> return. Every step should
be readable top to bottom without jumping through indirection.

Failure handling: every exit past classification carries a known
`request_id` (and, once routing has run, a known provider/model), so any
exception from here on is persisted as a `failed_requests` row via
`decision_service.record_failure()` before the HTTPException propagates —
see docs/architecture.md's "Failure handling" section. The one gap this
doesn't cover is an exception during classification/routing itself
(before a request_id-bearing failure record makes sense to write, since
routing_engine.select() and classifier.classify() are pure, in-process
logic with no external call to fail) — that case is a genuine programming
bug, not a degraded external dependency, and is left to surface as a 500
with a traceback rather than being silently swallowed into an audit row.
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
import httpx
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.schemas.routing import RoutingCandidate
from backend.schemas.routing_decision import RoutingTier
from backend.services import decision_service
from backend.services.classifier_service import ClassifierService, RoutingClassifierError, get_classifier_service
from backend.services.cost_estimator import estimate_cost
from backend.services.providers.factory import get_provider
from backend.services.quality_verifier import QualityVerifier, get_quality_verifier
from backend.services.routing_engine import RoutingEngine, get_routing_engine
from backend.utils.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_transient_provider_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, TimeoutError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


def _build_generation_prompt(prompt: str, tier: RoutingTier) -> str:
    if tier != RoutingTier.ADVANCED:
        return prompt

    # ponytail: one model call, no autonomous tool loop; add tools only when a real use case needs them
    return (
        "Act as a lightweight agent. Keep the work to three short stages: "
        "Plan, Final answer, Self-check. Show a concise plan, answer the user, "
        "then check the answer for missing requirements or obvious errors.\n\n"
        f"User request:\n{prompt}"
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    classifier: ClassifierService = Depends(get_classifier_service),
    engine: RoutingEngine = Depends(get_routing_engine),
    quality_verifier: QualityVerifier = Depends(get_quality_verifier),
) -> ChatResponse:
    prompt = body.prompt.strip()
    start = time.perf_counter()
    request_id = str(uuid.uuid4())

    try:
        decision_outcome = classifier.classify(prompt)
        routing_result = engine.select(decision_outcome.decision)
    except RoutingClassifierError as exc:
        logger.error("Both routing classifiers failed (request_id=%s): %s", request_id, exc)
        decision_service.record_failure(
            db, request_id=request_id, prompt=prompt, stage="routing_classifier",
            provider="openrouter", model=None, error_message=str(exc),
            created_at=datetime.now(timezone.utc),
        )
        raise HTTPException(status_code=503, detail="Routing classifiers unavailable") from exc

    candidates = routing_result.candidates or [
        RoutingCandidate(
            provider=routing_result.provider,
            model=routing_result.model,
            max_output_tokens=routing_result.max_output_tokens,
        )
    ]
    provider_response = None
    last_error = None
    generation_started = time.perf_counter()
    for index, candidate in enumerate(candidates):
        routing_result.provider = candidate.provider
        routing_result.model = candidate.model
        routing_result.max_output_tokens = candidate.max_output_tokens
        try:
            provider = get_provider(candidate.provider, settings)
            provider_response = provider.generate(
                _build_generation_prompt(prompt, routing_result.tier),
                candidate.model,
                max_tokens=candidate.max_output_tokens,
            )
            if index:
                routing_result.reasons.append(
                    f"Transient provider failure; fell back to {candidate.provider}/{candidate.model}"
                )
            break
        except Exception as exc:  # noqa: BLE001 - provider SDKs use different exception types
            last_error = exc
            if not _is_transient_provider_error(exc) or index == len(candidates) - 1:
                break
            logger.warning(
                "Transient provider failure; trying fallback (request_id=%s, provider=%s, model=%s): %s",
                request_id,
                candidate.provider,
                candidate.model,
                exc,
            )

    if provider_response is None:
        exc = last_error or RuntimeError("No routing candidate was available")
        logger.error(
            "Provider call failed (request_id=%s, provider=%s, model=%s): %s",
            request_id,
            routing_result.provider,
            routing_result.model,
            exc,
        )
        decision_service.record_failure(
            db,
            request_id=request_id,
            prompt=prompt,
            stage="provider_call",
            provider=routing_result.provider,
            model=routing_result.model,
            error_message=str(exc),
            created_at=datetime.now(timezone.utc),
        )
        raise HTTPException(
            status_code=502, detail=f"Model provider request failed: {exc}"
        ) from exc
    generation_latency_ms = round((time.perf_counter() - generation_started) * 1000, 2)

    try:
        model_cost = estimate_cost(
            routing_result.model, provider_response.input_tokens, provider_response.output_tokens
        )
    except Exception as exc:
        logger.error(
            "Cost estimation failed (request_id=%s, model=%s): %s", request_id, routing_result.model, exc
        )
        decision_service.record_failure(
            db,
            request_id=request_id,
            prompt=prompt,
            stage="cost_estimation",
            provider=routing_result.provider,
            model=routing_result.model,
            error_message=str(exc),
            created_at=datetime.now(timezone.utc),
        )
        raise HTTPException(
            status_code=502, detail=f"Cost estimation failed: {exc}"
        ) from exc

    total_cost = round(model_cost + decision_outcome.cost, 8)
    total_latency_ms = round((time.perf_counter() - start) * 1000, 2)
    timestamp = datetime.now(timezone.utc)

    # Only worth judging a cheaper tier's answer — the ADVANCED tier already
    # got the most capable model available, so there's nothing to compare it
    # against, and verifying it would just be extra cost for no signal.
    quality_verdict = None
    if routing_result.tier != RoutingTier.ADVANCED:
        quality_verdict = quality_verifier.verify(prompt, provider_response.text)

    try:
        decision_service.record(
            db,
            request_id=request_id,
            prompt=prompt,
            response=provider_response.text,
            created_at=timestamp,
            decision_outcome=decision_outcome,
            routing_result=routing_result,
            total_latency_ms=total_latency_ms,
            input_tokens=provider_response.input_tokens,
            output_tokens=provider_response.output_tokens,
            total_cost=total_cost,
            generation_cost=model_cost,
            generation_latency_ms=generation_latency_ms,
            provider_success=True,
            error_message=None,
            quality_verdict=quality_verdict,
        )
    except Exception as exc:
        logger.error("Failed to persist routing decision (request_id=%s): %s", request_id, exc)
        decision_service.record_failure(
            db,
            request_id=request_id,
            prompt=prompt,
            stage="persistence",
            provider=routing_result.provider,
            model=routing_result.model,
            error_message=str(exc),
            created_at=timestamp,
        )
        raise HTTPException(
            status_code=500, detail="Failed to persist routing decision"
        ) from exc

    return ChatResponse(
        request_id=request_id,
        prompt=prompt,
        response=provider_response.text,
        routing_tier=routing_result.tier.value,
        original_tier=routing_result.original_tier.value,
        escalated=routing_result.escalated,
        task_type=decision_outcome.decision.task_type,
        reasoning_level=decision_outcome.decision.reasoning_level.value,
        confidence=decision_outcome.decision.confidence,
        routing_reason=routing_result.reasons,
        classifier_model=decision_outcome.classifier_model,
        classifier_source=decision_outcome.classifier_source,
        fallback_used=decision_outcome.fallback_used,
        fallback_reason=decision_outcome.fallback_reason,
        calibrated_confidence=decision_outcome.calibrated_confidence,
        p_basic=decision_outcome.p_basic,
        p_standard=decision_outcome.p_standard,
        p_advanced=decision_outcome.p_advanced,
        provider=routing_result.provider,
        model=routing_result.model,
        input_tokens=provider_response.input_tokens,
        output_tokens=provider_response.output_tokens,
        classifier_cost=decision_outcome.cost,
        model_cost=model_cost,
        total_cost=total_cost,
        classifier_latency_ms=decision_outcome.latency_ms,
        generation_latency_ms=generation_latency_ms,
        total_latency_ms=total_latency_ms,
        quality_passed=quality_verdict.passed if quality_verdict else None,
        quality_reason=quality_verdict.reason if quality_verdict else None,
        timestamp=timestamp,
    )
