from everwild.rules import character as ch
from everwild.rules.death import die, recover_grave
from everwild.rules.items import add_to_bag, make_item


def test_death_creates_grave_and_resets(catalog, rng, make_char):
    hero = make_char("krieger", location="dorf")
    hero.location = "sumpf"
    hero.gold = 25
    for base in ("rubin", "silberkette", "trophaee", "rubin"):
        add_to_bag(catalog, hero, make_item(catalog, rng, base))
    add_to_bag(catalog, hero, make_item(catalog, rng, "questgegenstand", name="Mondschlüssel"))
    ch.set_xp(catalog, hero, 450, "mittel")
    weapon = hero.equipment.waffe

    result = die(catalog, rng, hero, turn=12, length="mittel")

    assert result.grave.location == "sumpf"
    assert result.grave.gold == 13 and hero.gold == 12
    # 5 non-quest bag slots (potion + 4 valuables) -> 3 lost
    assert len(result.grave.items) == 3
    assert any(i.name == "Mondschlüssel" for i in hero.bag)
    assert hero.equipment.waffe is weapon
    assert hero.xp == 400 and hero.level == 5 and result.xp_lost == 50
    assert hero.location == "dorf"
    assert hero.hp == ch.max_hp(catalog, hero)
    assert hero.cooldowns == {} and not hero.down


def test_second_death_destroys_old_grave(catalog, rng, make_char):
    hero = make_char()
    hero.location = "sumpf"
    first = die(catalog, rng, hero, turn=3, length="mittel").grave
    hero.location = "berg"
    second = die(catalog, rng, hero, turn=5, length="mittel")
    assert second.lost_grave == first
    assert hero.grave.location == "berg"


def test_recover_grave_only_at_its_location(catalog, rng, make_char):
    hero = make_char()
    hero.location = "sumpf"
    hero.gold = 10
    die(catalog, rng, hero, turn=3, length="mittel")
    assert recover_grave(catalog, hero) == (0, [])
    hero.location = "sumpf"
    gold, items = recover_grave(catalog, hero)
    assert gold == 5 and hero.gold == 10
    assert hero.grave is None
