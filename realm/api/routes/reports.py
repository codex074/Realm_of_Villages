"""Report routes: list and read (BUILD.md section 9, Phase 1)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from realm.api.deps import get_player, get_session
from realm.db.models import Player
from realm.services import reports
from realm.services.views import ReportDetail, ReportSummary

router = APIRouter()


@router.get("/reports", response_model=list[ReportSummary])
def list_reports(
    before_id: int | None = None,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> list[ReportSummary]:
    """Return the player's reports newest first, optionally before a given id."""
    return reports.list_reports(s, player.id, limit=50, before_id=before_id)


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(
    report_id: int,
    s: Session = Depends(get_session),  # noqa: B008
    player: Player = Depends(get_player),  # noqa: B008
) -> ReportDetail:
    """Return one of the player's reports and mark it read."""
    return reports.get_report(s, player.id, report_id)
