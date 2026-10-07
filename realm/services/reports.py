"""Player reports: create, list and read (BUILD.md 8.7)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from realm.db.models import Report
from realm.services.errors import FORBIDDEN, NOT_FOUND, GameError
from realm.services.views import ReportDetail, ReportSummary

REPORT_NOT_FOUND_TH = "ไม่พบรายงาน"
REPORT_FORBIDDEN_TH = "ไม่มีสิทธิ์ดูรายงานนี้"


def create_report(
    s: Session, player_id: int, kind: str, title: str, data: dict, now: datetime
) -> Report:
    """Create a report for a player and return the flushed row."""
    report = Report(
        player_id=player_id,
        kind=kind,
        title=title,
        data=data,
        is_read=False,
        created_at=now,
    )
    s.add(report)
    s.flush()
    return report


def list_reports(
    s: Session, player_id: int, limit: int = 50, before_id: int | None = None
) -> list[ReportSummary]:
    """The player's reports newest first (id descending), optionally before a given id."""
    stmt = select(Report).where(Report.player_id == player_id).order_by(Report.id.desc())
    if before_id is not None:
        stmt = stmt.where(Report.id < before_id)
    rows = s.scalars(stmt.limit(limit)).all()
    return [
        ReportSummary(
            id=r.id,
            kind=r.kind,
            title=r.title,
            created_at=r.created_at,
            is_read=r.is_read,
        )
        for r in rows
    ]


def get_report(s: Session, player_id: int, report_id: int, mark_read: bool = True) -> ReportDetail:
    """Fetch one of the player's reports; mark it read by default."""
    report = s.get(Report, report_id)
    if report is None:
        raise GameError(NOT_FOUND, REPORT_NOT_FOUND_TH)
    if report.player_id != player_id:
        raise GameError(FORBIDDEN, REPORT_FORBIDDEN_TH)
    if mark_read:
        report.is_read = True
        s.flush()
    return ReportDetail(
        id=report.id,
        kind=report.kind,
        title=report.title,
        created_at=report.created_at,
        is_read=report.is_read,
        data=report.data,
    )
