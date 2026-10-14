import pytest

from everwild.rules.dice import check, combine_advantage, parse_dice, roll_d20, roll_dice, seeded_rng

from conftest import FixedRng


def test_parse_dice():
    assert parse_dice("1d8") == (1, 8)
    assert parse_dice("2d6") == (2, 6)
    with pytest.raises(ValueError):
        parse_dice("d8")


def test_seeded_rng_is_reproducible():
    assert roll_dice(seeded_rng("spiel", 3), "5d20") == roll_dice(seeded_rng("spiel", 3), "5d20")
    assert roll_dice(seeded_rng("spiel", 3), "5d20") != roll_dice(seeded_rng("spiel", 4), "5d20")


def test_advantage_keeps_higher_and_disadvantage_lower():
    assert roll_d20(FixedRng([5, 17]), "vorteil").kept == 17
    assert roll_d20(FixedRng([5, 17]), "nachteil").kept == 5


def test_advantage_and_disadvantage_cancel_and_do_not_stack():
    assert combine_advantage("vorteil", "nachteil") == "normal"
    assert combine_advantage("vorteil", "vorteil", "normal") == "vorteil"
    assert combine_advantage("nachteil") == "nachteil"


@pytest.mark.parametrize("roll,modifier,target,outcome", [
    (20, -10, 30, "kritischer_erfolg"),
    (1, 30, 5, "kritischer_fehlschlag"),
    (12, 3, 12, "erfolg"),
    (9, 1, 12, "erfolg_mit_haken"),
    (8, 1, 12, "fehlschlag"),
])
def test_check_outcomes(roll, modifier, target, outcome):
    result = check(FixedRng([roll]), modifier, target)
    assert result.outcome == outcome
    assert result.total == roll + modifier
