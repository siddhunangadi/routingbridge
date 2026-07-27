"""Read-side queries for GET /agent/report/{id} and GET /agent/reports.
Pure retrieval of what routing_agent.investigate() already persisted —
this module writes nothing, same read/write split PR2 established
between analytics_service.py and routing_learning.py.
"""

from sqlalchemy.orm import Session

from backend.database.models import InvestigationReport as InvestigationReportModel
from backend.schemas.investigation import Finding, InvestigationReport, InvestigationReportSummary, SuggestedAction


def get_report(db: Session, report_id: str) -> InvestigationReport | None:
    row = db.get(InvestigationReportModel, report_id)
    if row is None:
        return None
    return InvestigationReport(
        report_id=row.report_id,
        created_at=row.created_at,
        policy_version=row.policy_version,
        executive_summary=row.executive_summary,
        findings=[Finding.model_validate(f) for f in row.findings],
        suggested_actions=[SuggestedAction.model_validate(a) for a in row.suggested_actions],
        risk_level=row.risk_level,
        confidence=row.confidence,
        investigation_steps=row.investigation_steps,
        tools_used=row.tools_used,
    )


def list_reports(db: Session, *, limit: int, offset: int) -> list[InvestigationReportSummary]:
    rows = (
        db.query(InvestigationReportModel)
        .order_by(InvestigationReportModel.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        InvestigationReportSummary(
            report_id=row.report_id,
            created_at=row.created_at,
            policy_version=row.policy_version,
            executive_summary=row.executive_summary,
            risk_level=row.risk_level,
            confidence=row.confidence,
        )
        for row in rows
    ]
