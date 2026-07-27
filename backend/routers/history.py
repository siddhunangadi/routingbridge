"""GET /history — most recent chat requests, newest first."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.schemas.history import HistoryItem
from backend.services import history_service

router = APIRouter()


@router.get("/history", response_model=list[HistoryItem])
def get_history(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[HistoryItem]:
    return history_service.get_history(db, limit=limit, offset=offset)
