"""Village slot layout: field types, slot rules and the initial village (BUILD.md 6.2)."""

from realm.core.config import GameConfig

FIELD_SLOTS = range(1, 19)
CENTER_SLOTS = range(20, 39)
ALL_SLOTS = range(1, 41)

_LAYOUT_ORDER = ("woodcutter", "quarry", "iron_mine", "farm")


def field_types_for_layout(layout: str) -> dict[int, str]:
    """Map field slots 1..18 to field types from a layout string 'a-b-c-d'."""
    counts = [int(part) for part in layout.split("-")]
    if len(counts) != 4 or sum(counts) != len(FIELD_SLOTS):
        raise ValueError(f"bad layout '{layout}': expected 4 parts summing to {len(FIELD_SLOTS)}")
    out: dict[int, str] = {}
    slot = 1
    for btype, count in zip(_LAYOUT_ORDER, counts, strict=True):
        for _ in range(count):
            out[slot] = btype
            slot += 1
    return out


def slot_accepts(slot: int, btype: str, cfg: GameConfig, layout: str) -> bool:
    """Whether a building type may be built on the given slot of the given layout."""
    bd = cfg.buildings[btype]
    if slot in FIELD_SLOTS:
        return bd.kind == "field" and field_types_for_layout(layout).get(slot) == btype
    if slot in CENTER_SLOTS:
        return bd.kind == "center"
    if bd.kind == "fixed":
        return bd.fixed_slot == slot
    return False


def initial_buildings(layout: str, cfg: GameConfig) -> dict[int, tuple[str, int]]:
    """Fresh village: 18 level-0 fields, town hall level 1, rally point and wall level 0."""
    out: dict[int, tuple[str, int]] = {
        slot: (btype, 0) for slot, btype in field_types_for_layout(layout).items()
    }
    for bd in cfg.buildings.values():
        if bd.kind == "fixed":
            out[bd.fixed_slot] = (bd.key, 1 if bd.key == "town_hall" else 0)
    return out
