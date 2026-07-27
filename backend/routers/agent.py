"""POST /agent/investigate, GET /agent/report/{id}, GET /agent/reports —
the Routing Optimization Agent. Offline and read-only with respect to
routing: it only ever writes to investigation_reports. See
docs/pr4-routing-agent.md.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database.db import get_db
from backend.schemas.investigation import InvestigationReport, InvestigationReportSummary
from backend.services import investigation_service, routing_agent

router = APIRouter(prefix="/agent")


@router.post("/investigate", response_model=InvestigationReport)
def run_investigation(db: Session = Depends(get_db)) -> InvestigationReport:
    return routing_agent.investigate(db)


@router.get("/reports", response_model=list[InvestigationReportSummary])
def list_investigation_reports(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[InvestigationReportSummary]:
    return investigation_service.list_reports(db, limit=limit, offset=offset)


@router.get("/report/{report_id}", response_model=InvestigationReport)
def get_investigation_report(report_id: str, db: Session = Depends(get_db)) -> InvestigationReport:
    report = investigation_service.get_report(db, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No investigation report found for report_id '{report_id}'")
    return report
