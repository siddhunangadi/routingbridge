"""GET/POST /analytics/* — routing performance, learned patterns, and
optimization recommendations. All read endpoints query what PR1 already
persists; /refresh is the only write, and only routing_learning.py does it.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.schemas.analytics import (
    RecommendationResponse,
    RefreshResult,
    RoutingOverviewResponse,
    RoutingPatternResponse,
)
from backend.services import analytics_service, routing_learning
from backend.services.routing_evaluation import benchmark

router = APIRouter(prefix="/analytics")


@router.get("/benchmark")
def get_router_benchmark() -> dict[str, object]:
    return benchmark()


@router.post("/refresh", response_model=RefreshResult)
def refresh_analytics(db: Session = Depends(get_db)) -> RefreshResult:
    return routing_learning.refresh(db)


@router.get("/routing", response_model=RoutingOverviewResponse)
def get_routing_analytics(db: Session = Depends(get_db)) -> RoutingOverviewResponse:
    return analytics_service.get_routing_overview(db)


@router.get("/patterns", response_model=list[RoutingPatternResponse])
def get_routing_patterns(db: Session = Depends(get_db)) -> list[RoutingPatternResponse]:
    return analytics_service.get_patterns(db)


@router.get("/recommendations", response_model=list[RecommendationResponse])
def get_optimization_recommendations(
    db: Session = Depends(get_db),
) -> list[RecommendationResponse]:
    return analytics_service.get_recommendations(db)
