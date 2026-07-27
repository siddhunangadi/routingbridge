"""GET /routing/decision/{request_id} — the DecisionCard explaining one
past routing decision, plus its matching recommendation if one exists.
Read-only: never changes routing, never touches routing.yaml.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.schemas.decision_card import DecisionDetailResponse
from backend.services import decision_service

router = APIRouter(prefix="/routing")


@router.get("/decision/{request_id}", response_model=DecisionDetailResponse)
def get_routing_decision(request_id: str, db: Session = Depends(get_db)) -> DecisionDetailResponse:
    result = decision_service.get_decision_card(db, request_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No routing decision found for request_id '{request_id}'")

    card, recommendation = result
    return DecisionDetailResponse(decision_card=card, recommendation=recommendation)
