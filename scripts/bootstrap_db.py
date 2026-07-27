"""One-time/explicit database bootstrap: create tables, seed the active
routing policy.

Table creation here uses `Base.metadata.create_all()` — the same
idempotent DDL the app's own startup runs — so this script is safe to
run standalone (e.g. once against a fresh Supabase/Postgres database)
without needing the app to have started first. Seeding the active
`routing_policies` row stays a deliberate, explicit step rather than
something that runs on every FastAPI startup: it's business data (an
audit trail of which policy versions have ever been active), and an app
boot is not an event that should write it.

Usage:
    python -m scripts.bootstrap_db
"""

import logging

from backend.database.db import Base, SessionLocal, engine
from backend.database.models import RoutingPolicy
from backend.utils.logging_setup import configure_logging
from backend.utils.yaml_config import load_routing_config

logger = logging.getLogger(__name__)


def bootstrap() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Tables created (or already present)")

    routing_cfg = load_routing_config()
    version = routing_cfg.get("policy_version", "v1.0")

    db = SessionLocal()
    try:
        if db.get(RoutingPolicy, version) is None:
            db.add(RoutingPolicy(version=version, config=routing_cfg["tiers"], is_active=True))
            db.commit()
            logger.info("Seeded routing policy %s", version)
        else:
            logger.info("Routing policy %s already exists, skipping seed", version)
    finally:
        db.close()


if __name__ == "__main__":
    configure_logging("INFO")
    bootstrap()
