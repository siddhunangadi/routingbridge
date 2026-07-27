"""RoutingBridge FastAPI application entrypoint."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.routers import agent, analytics, chat, decisions, history, models, stats
from backend.utils.config import get_settings
from backend.utils.logging_setup import configure_logging
from backend.utils.startup_validation import validate_startup_config

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    # Fail fast: a routing.yaml/pricing.yaml mismatch (unknown provider,
    # unpriced model, inverted confidence thresholds) should stop the app
    # from serving traffic, not surface as a 500 on the first request that
    # happens to hit the broken tier. See docs/architecture.md.
    validate_startup_config()
    logger.info("Routing/pricing configuration validated")

    # Schema creation and policy seeding both happen in
    # `python -m scripts.bootstrap_db`, run once explicitly (locally or as
    # a deploy step) — not here. Two reasons: seeding routing_policies is
    # business data an app boot shouldn't silently write, and even the
    # idempotent create_all() DDL means a real DB round-trip on every
    # boot, which is wasted work (and, against a remote Postgres, real
    # latency) for a schema that only changes when a model does.
    logger.info("RoutingBridge API starting up")
    yield


app = FastAPI(
    title="RoutingBridge",
    description=(
        "Explainable, self-learning multi-LLM routing platform: classifies each "
        "prompt, routes it to the cheapest capable model, records a full decision "
        "audit trail, and offline-analyzes its own routing history for "
        "optimization opportunities — all advisory, all human-approved."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(chat.router, tags=["chat"])
app.include_router(history.router, tags=["history"])
app.include_router(stats.router, tags=["stats"])
app.include_router(models.router, tags=["models"])
app.include_router(analytics.router, tags=["analytics"])
app.include_router(decisions.router, tags=["decisions"])
app.include_router(agent.router, tags=["agent"])


@app.get("/health")
def health() -> dict:
    """Liveness check used by Docker/monitoring to confirm the API is up."""
    return {"status": "ok"}
