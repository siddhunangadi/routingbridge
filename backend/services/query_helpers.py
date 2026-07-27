"""Shared SQLAlchemy query building blocks used by more than one service.

Kept intentionally tiny: this exists only because PASS_RATE was
duplicated verbatim across analytics_service.py, routing_learning.py,
and routing_agent.py. Add to this file only when a second real user of
a query fragment shows up — don't pre-populate it speculatively.
"""

from sqlalchemy import case, func

from backend.database.models import QualityResult

# AVG ignores NULL: rows with no quality_results row (outer-joined NULL
# verdict) drop out of the average entirely, instead of counting as a
# failure — pass_rate is "of the requests we actually verified", same
# semantics as /stats' quality_pass_rate.
PASS_RATE = func.avg(
    case((QualityResult.verdict.is_(True), 1.0), (QualityResult.verdict.is_(False), 0.0), else_=None)
)
