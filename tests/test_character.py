import pytest

from everwild.rules import character as ch


def test_starting_characters(catalog, make_char):
    krieger = make_char("krieger")
    assert krieger.hp == 14
    assert krieger.abilities == ["wuchtschlag"]
    assert krieger.gold == catalog.rules.starting_gold
    # 10 + Kettenhemd 2 + Schild 1 + Krieger 1
    assert ch.armor_value(catalog, krieger) == 14
    assert [i.base for i in krieger.bag] == ["heiltrank"]

    schurke = make_char("schurke")
    assert {i.base for i in schurke.bag} == {"dietriche", "heiltrank"}

    magier = make_char("magier", element="wasser")
    scroll = next(i for i in magier.bag if i.base == "schriftrolle")
    assert scroll.element == "wasser"


def test_attack_profiles(catalog, make_char):
    krieger = ch.attack_profile(catalog, make_char("krieger", element="stahl"))
    assert (krieger.dice, krieger.attack_bonus, krieger.damage_bonus) == ("1d8", 3, 3)
    assert krieger.damage_label == "d8 + 3"

    # light weapons use the better of STÄ and GES
    schurke = ch.attack_profile(catalog, make_char("schurke", element="stahl"))
    assert schurke.attribute == "geschick"

    # Kleriker and Barde fight with Verstand
    assert ch.attack_profile(catalog, make_char("kleriker", element="stahl")).attribute == "verstand"
    assert ch.attack_profile(catalog, make_char("barde", element="stahl")).attribute == "verstand"

    # bows are ranged and stay on Geschick
    assert ch.attack_profile(catalog, make_char("waldlaeufer", element="stahl")).attribute == "geschick"


def xp(catalog, level, length="mittel"):
    return ch.level_start_xp(catalog, level, length)


def test_magier_spell_grows_and_uses_element(catalog, make_char):
    magier = make_char("magier", element="feuer")
    profile = ch.attack_profile(catalog, magier)
    assert profile.spell and profile.element == "feuer"
    assert profile.dice == "1d6"
    # VER 3 + Stab 1
    assert profile.damage_bonus == 4
    # VER 3 + affinity 1 in the spell's element
    assert profile.attack_bonus == 4
    ch.set_xp(catalog, magier, xp(catalog, 4), "mittel")
    assert ch.attack_profile(catalog, magier).dice == "1d8"
    ch.set_xp(catalog, magier, xp(catalog, 8), "mittel")
    assert ch.attack_profile(catalog, magier).dice == "1d10"


def test_levels_follow_game_length(catalog, make_char):
    hero = make_char("krieger")
    events = ch.set_xp(catalog, hero, xp(catalog, 4) + 40, "mittel")
    assert hero.level == 4
    assert [e.level for e in events] == [2, 3, 4]
    assert ch.max_hp(catalog, hero) == 14 + 3 * 5
    assert hero.hp == ch.max_hp(catalog, hero)
    per_level = catalog.rules.game_lengths["kurz"].xp_per_level
    assert ch.level_for_xp(catalog, 3 * per_level + 1, "kurz") == 4
    assert ch.level_for_xp(catalog, 99999, "lang") == 10


def test_hp_per_level_differs_by_class(catalog, make_char):
    for class_id, gain in (("krieger", 5), ("kleriker", 3), ("waldlaeufer", 3),
                           ("schurke", 2), ("barde", 2), ("magier", 1)):
        hero = make_char(class_id)
        ch.set_xp(catalog, hero, xp(catalog, 2), "mittel")
        assert ch.max_hp(catalog, hero) - catalog.classes[class_id].hp == gain


def test_attribute_increase_uses_choice_or_main_attribute(catalog, make_char):
    default = make_char("schurke")
    ch.set_xp(catalog, default, xp(catalog, 3), "mittel")
    assert default.attribute_increases == ["geschick"]

    chosen = make_char("schurke")
    chosen.attribute_choice = "verstand"
    ch.set_xp(catalog, chosen, xp(catalog, 3), "mittel")
    assert chosen.attribute_increases == ["verstand"]
    assert chosen.attribute_choice is None


def test_attributes_are_capped(catalog, make_char):
    hero = make_char("krieger")
    hero.attribute_increases = ["staerke"] * 5
    assert ch.attribute(catalog, hero, "staerke") == catalog.rules.max_attribute


def test_second_ability_chosen_in_advance(catalog, make_char):
    hero = make_char("kleriker")
    ch.choose_second_ability(catalog, hero, "schutzsegen")
    events = ch.set_xp(catalog, hero, xp(catalog, 5), "mittel")
    assert hero.abilities == ["heilung", "schutzsegen"]
    assert events[-1].ability_granted == "schutzsegen"


def test_second_ability_offered_then_random(catalog, rng, make_char):
    hero = make_char("barde")
    events = ch.set_xp(catalog, hero, xp(catalog, 5), "mittel", turn=10)
    assert events[-1].ability_offered == catalog.classes["barde"].second_abilities
    assert ch.resolve_pending_ability(catalog, rng, hero, turn=10) is None
    granted = ch.resolve_pending_ability(catalog, rng, hero, turn=11)
    assert granted in catalog.classes["barde"].second_abilities
    assert hero.abilities[-1] == granted


def test_wrong_second_ability_is_rejected(catalog, make_char):
    with pytest.raises(ch.CharacterError):
        ch.choose_second_ability(catalog, make_char("krieger"), "feuerball")


def test_catch_up_bonus(catalog, make_char):
    hero = make_char()
    gained, _ = ch.add_xp(catalog, hero, 20, "mittel", average_level=3)
    assert gained == 30
    gained, _ = ch.add_xp(catalog, hero, 20, "mittel", average_level=1)
    assert gained == 20


def test_cooldown_ready_three_turns_later(catalog, make_char):
    hero = make_char()
    ch.use_ability(catalog, hero, "wuchtschlag")
    with pytest.raises(ch.CharacterError):
        ch.use_ability(catalog, hero, "wuchtschlag")
    for _ in range(2):
        ch.tick_cooldowns(hero)
        assert not ch.ability_ready(hero, "wuchtschlag")
    ch.tick_cooldowns(hero)
    assert ch.ability_ready(hero, "wuchtschlag")


def test_class_change_only_in_first_turns(catalog, rng, make_char):
    hero = make_char("krieger", turn=5)
    hero.gold = 33
    changed = ch.change_class(catalog, rng, hero, "magier", element="luft", turn=7, length="mittel")
    assert changed.class_id == "magier"
    assert changed.element == "luft"
    assert changed.gold == 33
    assert changed.abilities == ["feuerball"]
    with pytest.raises(ch.CharacterError):
        ch.change_class(catalog, rng, changed, "barde", turn=8, length="mittel")


def test_heal_wakes_down_character(catalog, make_char):
    hero = make_char()
    hero.hp, hero.down = 0, True
    assert ch.heal(catalog, hero, 100) == 14
    assert not hero.down
