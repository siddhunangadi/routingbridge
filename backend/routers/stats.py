"""GET /stats — aggregate analytics for the dashboard."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.schemas.stats import StatsResponse
from backend.services import stats_service

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    return stats_service.get_stats(db)
