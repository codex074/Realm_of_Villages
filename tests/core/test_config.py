import shutil
from pathlib import Path

import pytest
import yaml

from realm.core.config import GameConfig, load_config

REAL = Path(__file__).resolve().parents[2] / "realm" / "config"


def test_real_config_loads():
    cfg = load_config()
    assert isinstance(cfg, GameConfig)
    assert len(cfg.buildings) == 17
    assert len(cfg.units) == 9
    assert len(cfg.tribes) == 3
    assert len(cfg.personalities) == 5
    assert cfg.buildings["woodcutter"].key == "woodcutter"
    assert cfg.units["spearman"].key == "spearman"
    assert cfg.world.start_resources.wood == 750


def test_load_config_is_cached():
    assert load_config() is load_config()


def test_build_order_parsed():
    order = load_config().personalities["farmer"].build_order
    assert order[0] == ("warehouse", 1)
    assert ("town_hall", 3) in order


@pytest.fixture
def bad(tmp_path):
    """Copy the real config to tmp_path and return a mutator for one file."""
    for f in REAL.glob("*.yaml"):
        shutil.copy(f, tmp_path / f.name)

    def mutate(name, fn):
        path = tmp_path / name
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        fn(data)
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return tmp_path

    return mutate


def test_unmodified_copy_is_valid(bad):
    assert len(load_config(bad("game.yaml", lambda d: None)).buildings) == 17


def test_building_requires_unknown(bad):
    d = bad("buildings.yaml", lambda d: d["stable"]["requires"].update({"nope": 1}))
    with pytest.raises(ValueError, match="nope"):
        load_config(d)


def test_unit_requires_unknown(bad):
    d = bad("units.yaml", lambda d: d["spearman"]["requires"].update({"nope": 1}))
    with pytest.raises(ValueError, match="nope"):
        load_config(d)


def test_trained_in_unknown(bad):
    d = bad("units.yaml", lambda d: d["spearman"].update({"trained_in": "nope"}))
    with pytest.raises(ValueError, match="trained_in"):
        load_config(d)


def test_field_needs_produces(bad):
    d = bad("buildings.yaml", lambda d: d["farm"].pop("produces"))
    with pytest.raises(ValueError, match="produces"):
        load_config(d)


def test_fixed_needs_slot(bad):
    d = bad("buildings.yaml", lambda d: d["wall"].pop("fixed_slot"))
    with pytest.raises(ValueError, match="fixed_slot"):
        load_config(d)


def test_unit_mix_unknown_unit(bad):
    d = bad("bots.yaml", lambda d: d["personalities"]["farmer"]["unit_mix"].update({"nope": 1}))
    with pytest.raises(ValueError, match="nope"):
        load_config(d)


def test_build_order_unknown_building(bad):
    d = bad("bots.yaml", lambda d: d["personalities"]["farmer"]["build_order"].append("nope:1"))
    with pytest.raises(ValueError, match="nope"):
        load_config(d)


def test_build_order_bad_format(bad):
    d = bad("bots.yaml", lambda d: d["personalities"]["farmer"]["build_order"].append("wall"))
    with pytest.raises(ValueError, match="build_order"):
        load_config(d)


def test_personality_shares_sum(bad):
    d = bad("bots.yaml", lambda d: d["personalities"]["farmer"].update({"share": 0.5}))
    with pytest.raises(ValueError, match="shares"):
        load_config(d)


def test_difficulty_shares_sum(bad):
    d = bad("bots.yaml", lambda d: d["difficulty_shares"].update({"easy": 0.9}))
    with pytest.raises(ValueError, match="difficulty_shares"):
        load_config(d)


def test_tile_weights_sum(bad):
    d = bad("game.yaml", lambda d: d["world"]["tile_weights"].update({"lake": 50}))
    with pytest.raises(ValueError, match="tile_weights"):
        load_config(d)
