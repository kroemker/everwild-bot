from everwild.rules import elements as el


def test_matchups(catalog):
    assert el.matchup(catalog, "wasser", ["feuer"]) == "stark"
    assert el.matchup(catalog, "feuer", ["feuer"]) == "schwach"
    assert el.matchup(catalog, "feuer", ["erde"]) == "neutral"
    assert el.matchup(catalog, "stahl", ["feuer"]) == "neutral"
    assert el.matchup(catalog, "licht", []) == "neutral"
    # a target with both the attack element and its opposite cancels out
    assert el.matchup(catalog, "wasser", ["wasser", "feuer"]) == "neutral"


def test_multiplier_rounds_half_up_and_keeps_at_least_one(catalog):
    assert el.apply_multiplier(5, 1.5) == 8
    assert el.apply_multiplier(5, 0.5) == 3
    assert el.apply_multiplier(1, 0.5) == 1
    assert el.apply_multiplier(0, 1.5) == 0


def test_starting_element_gives_affinity_one(make_char):
    assert make_char(element="luft").affinity == {"luft": 1}
    assert make_char(element="stahl").affinity == {}


def test_affinity_limits(catalog, make_char):
    hero = make_char(element="feuer")
    assert not el.gain_affinity(catalog, hero, "wasser")  # opposite
    assert el.gain_affinity(catalog, hero, "erde")
    assert not el.gain_affinity(catalog, hero, "licht")  # third element
    assert el.gain_affinity(catalog, hero, "feuer")
    assert el.gain_affinity(catalog, hero, "feuer")
    assert not el.gain_affinity(catalog, hero, "feuer")  # max 3
    assert hero.affinity == {"feuer": 3, "erde": 1}


def test_talisman_adds_affinity_and_resistance(catalog, rng, make_char):
    from everwild.rules.items import make_item
    hero = make_char(element="feuer")
    assert not el.resists(catalog, hero, "feuer")
    hero.equipment.talisman = make_item(catalog, rng, "talisman", rarity="selten", element="feuer")
    assert el.effective_affinity(catalog, hero, "feuer") == 2
    assert el.resists(catalog, hero, "feuer")
