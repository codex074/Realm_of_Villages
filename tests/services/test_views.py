"""Tests for realm.services.views pydantic models."""

from datetime import UTC, datetime

from realm.services.views import (
    BuildingView,
    MovementView,
    ReportDetail,
    ReportSummary,
    VillageBrief,
    VillageView,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_village_view_with_40_buildings_serialises() -> None:
    """VillageView accepts 40 BuildingView entries and serialises with model_dump(mode='json')."""
    buildings = [BuildingView(slot=i, type=None, level=0, name_th=None) for i in range(1, 41)]
    view = VillageView(
        game_now=T0,
        village=VillageBrief(id=1, name="v", x=0, y=0, is_capital=True, population=10),
        tribe="human",
        loyalty=100.0,
        resources={"wood": 1.0},
        rates={"wood": 2.0},
        capacity={"wood": 100.0},
        hidden=0.0,
        buildings=buildings,
        build_queue=[],
        queue_limit=1,
        troops_home={"swordsman": 5},
        reinforcements_here=[],
        troops_away=[],
        training=[],
        movements=[],
    )
    data = view.model_dump(mode="json")
    assert len(data["buildings"]) == 40
    assert data["village"]["name"] == "v"
    assert datetime.fromisoformat(data["game_now"]) == T0
    assert data["troops_home"] == {"swordsman": 5}


def test_movement_view_units_may_be_none() -> None:
    """MovementView.units is optional and accepts None."""
    mv = MovementView(
        id=1,
        mission="return",
        direction="in",
        from_village=VillageBrief(id=2, name="a", x=1, y=1, is_capital=False, population=5),
        to={"x": 0, "y": 0},
        to_village_name="v",
        arrive_at=T0,
        units=None,
        hostile=False,
    )
    assert mv.units is None
    assert mv.model_dump()["units"] is None


def test_report_detail_inherits_summary_fields() -> None:
    """ReportDetail accepts all ReportSummary fields plus data."""
    detail = ReportDetail(
        id=3,
        kind="battle",
        title="t",
        created_at=T0,
        is_read=False,
        data={"loot": {"wood": 10}},
    )
    assert isinstance(detail, ReportSummary)
    assert detail.kind == "battle"
    assert detail.data == {"loot": {"wood": 10}}
