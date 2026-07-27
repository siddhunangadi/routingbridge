"""analytics_service: read-side aggregation for GET /analytics/routing.
Uses the _record fixture helper from test_routing_learning to
populate realistic rows.
"""

from backend.services import analytics_service
from tests.test_routing_learning import _record


def test_routing_overview_aggregates_by_provider_model_task_and_tier(db_session):
    _record(db_session, "r1", "google", "gemini-2.5-flash", True, cost=0.0001, latency=100.0)
    _record(db_session, "r2", "google", "gemini-2.5-flash", False, cost=0.0003, latency=300.0)

    overview = analytics_service.get_routing_overview(db_session)

    assert len(overview.providers) == 1
    provider_stats = overview.providers[0]
    assert provider_stats.provider == "google"
    assert provider_stats.request_count == 2
    assert provider_stats.average_cost == 0.0002
    assert provider_stats.pass_rate == 0.5

    assert len(overview.models) == 1
    assert overview.models[0].model == "gemini-2.5-flash"

    assert len(overview.task_types) == 1
    assert overview.task_types[0].task_type == "Programming"

    assert overview.tier_distribution == {"BASIC": 2}
    assert len(overview.daily_metrics) == 1
    assert overview.daily_metrics[0].request_count == 2


def test_routing_overview_empty_database(db_session):
    overview = analytics_service.get_routing_overview(db_session)

    assert overview.providers == []
    assert overview.models == []
    assert overview.task_types == []
    assert overview.tier_distribution == {}
    assert overview.daily_metrics == []


def test_patterns_and_recommendations_empty_before_refresh(db_session):
    assert analytics_service.get_patterns(db_session) == []
    assert analytics_service.get_recommendations(db_session) == []
