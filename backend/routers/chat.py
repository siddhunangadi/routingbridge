"""POST /chat — the core request flow: classify, route, call the selected
model, estimate cost, persist, respond.

This function is intentionally a straight line, not a pipeline abstraction:
classify -> route -> generate -> cost -> save -> return. A fresher should
be able to read it top to bottom and narrate every step in an interview.
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import RequestLog
from backend.schemas.chat import ChatRequest, ChatResponse
from backend.services.classifier_service import ClassifierService, get_classifier_service
from backend.services.cost_estimator import estimate_cost
from backend.services.providers.factory import get_provider
from backend.services.routing_engine import RoutingEngine, get_routing_engine
from backend.utils.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    classifier: ClassifierService = Depends(get_classifier_service),
    engine: RoutingEngine = Depends(get_routing_engine),
) -> ChatResponse:
    prompt = body.prompt.strip()
    start = time.perf_counter()

    decision_outcome = classifier.classify(prompt)
    routing_result = engine.select(decision_outcome.decision)

    provider = get_provider(routing_result.provider, settings)
    try:
        provider_response = provider.generate(
            prompt, routing_result.model, max_tokens=routing_result.max_output_tokens
        )
    except Exception as exc:
        logger.error(
            "Provider call failed (provider=%s, model=%s): %s",
            routing_result.provider,
            routing_result.model,
            exc,
        )
        raise HTTPException(
            status_code=502, detail=f"Model provider request failed: {exc}"
        ) from exc

    model_cost = estimate_cost(
        routing_result.model, provider_response.input_tokens, provider_response.output_tokens
    )
    total_cost = round(model_cost + decision_outcome.cost, 8)
    total_latency_ms = round((time.perf_counter() - start) * 1000, 2)
    request_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)

    db.add(
        RequestLog(
            id=request_id,
            timestamp=timestamp,
            prompt=prompt,
            response=provider_response.text,
            routing_tier=routing_result.tier.value,
            original_tier=routing_result.original_tier.value,
            escalated=routing_result.escalated,
            task_type=decision_outcome.decision.task_type,
            reasoning_level=decision_outcome.decision.reasoning_level.value,
            confidence=decision_outcome.decision.confidence,
            routing_reason=" | ".join(routing_result.reasons),
            classifier_model=decision_outcome.classifier_model,
            classifier_latency_ms=decision_outcome.latency_ms,
            classifier_cost=decision_outcome.cost,
            fallback_used=decision_outcome.fallback_used,
            provider=routing_result.provider,
            model=routing_result.model,
            input_tokens=provider_response.input_tokens,
            output_tokens=provider_response.output_tokens,
            model_cost=model_cost,
            total_cost=total_cost,
            total_latency_ms=total_latency_ms,
        )
    )
    db.commit()

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
        fallback_used=decision_outcome.fallback_used,
        provider=routing_result.provider,
        model=routing_result.model,
        input_tokens=provider_response.input_tokens,
        output_tokens=provider_response.output_tokens,
        classifier_cost=decision_outcome.cost,
        model_cost=model_cost,
        total_cost=total_cost,
        total_latency_ms=total_latency_ms,
        timestamp=timestamp,
    )
