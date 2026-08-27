"""scripts/bootstrap_db: creates tables and seeds the active routing policy
exactly once — the explicit replacement for the startup auto-seed PR1's
review flagged."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.database.models import RoutingPolicy
from scripts import bootstrap_db


def _bootstrap_against(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(bootstrap_db, "engine", engine)
    monkeypatch.setattr(bootstrap_db, "SessionLocal", session_factory)
    return engine, session_factory


def test_bootstrap_creates_all_tables(monkeypatch):
    engine, _ = _bootstrap_against(monkeypatch)

    bootstrap_db.bootstrap()

    table_names = set(inspect(engine).get_table_names())
    assert {
        "requests",
        "routing_decisions",
        "execution_results",
        "quality_results",
        "routing_policies",
        "routing_patterns",
        "optimization_recommendations",
        "investigation_reports",
    } <= table_names


def test_bootstrap_seeds_routing_policy_once(monkeypatch):
    _, session_factory = _bootstrap_against(monkeypatch)

    bootstrap_db.bootstrap()
    bootstrap_db.bootstrap()  # idempotent: must not raise or duplicate

    session = session_factory()
    try:
        policies = session.query(RoutingPolicy).all()
        assert len(policies) == 1
        assert policies[0].version == "v2.1"
        assert policies[0].is_active is True
    finally:
        session.close()


def test_metadata_migration_is_idempotent_for_existing_tables(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE routing_decisions (request_id VARCHAR PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE execution_results (request_id VARCHAR PRIMARY KEY)"))
    monkeypatch.setattr(bootstrap_db, "engine", engine)

    bootstrap_db.add_routing_metadata_columns()
    bootstrap_db.add_routing_metadata_columns()

    assert "classifier_source" in {column["name"] for column in inspect(engine).get_columns("routing_decisions")}
    assert "generation_cost" in {column["name"] for column in inspect(engine).get_columns("execution_results")}
