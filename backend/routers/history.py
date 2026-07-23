"""GET /history — most recent chat requests, newest first."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.database.models import RequestLog
from backend.schemas.history import HistoryItem

router = APIRouter()


@router.get("/history", response_model=list[HistoryItem])
def get_history(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[RequestLog]:
    return (
        db.query(RequestLog)
        .order_by(desc(RequestLog.timestamp))
        .offset(offset)
        .limit(limit)
        .all()
    )
