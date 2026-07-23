"""ModelPilot FastAPI application entrypoint."""

import logging

from fastapi import FastAPI

from backend.database.db import Base, engine
from backend.routers import chat
from backend.utils.config import get_settings
from backend.utils.logging_setup import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ModelPilot",
    description="Intelligent Multi-LLM Routing & Cost Optimization Platform",
    version="0.1.0",
)

app.include_router(chat.router, tags=["chat"])


@app.get("/health")
def health() -> dict:
    """Liveness check used by Docker/monitoring to confirm the API is up."""
    return {"status": "ok"}


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("ModelPilot API starting up")
