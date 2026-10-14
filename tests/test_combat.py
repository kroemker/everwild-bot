import random

from everwild.rules import character as ch
from everwild.rules.combat import Tactic, resolve_fight
from everwild.rules.enemies import EnemySpec, build_enemies


def foes(catalog, n=1, tier="normal", elements=(), **stats):
    enemies = build_enemies(catalog, [EnemySpec("Wolf", tier, tuple(elements), n)], 1, 1)
    for enemy in enemies:
        for key, value in stats.items():
            setattr(enemy, key, value)
    return enemies


def attack(*heroes):
    return {h.id: Tactic("angriff") for h in heroes}


def test_strong_party_wins_and_logs_attacks(catalog, make_char):
    hero = make_char("krieger")
    enemies = foes(catalog, hp=1, defense=1, attack=-50)
    result = resolve_fight(catalog, random.Random(1), [hero], attack(hero), enemies)
    assert result.outcome == "gewonnen"
    assert result.participants == [hero.id]
    assert result.defeated == enemies
    kinds = [e.kind for e in result.events]
    assert "angriff" in kinds and kinds[-1] == "gegner_besiegt"


def test_idle_player_defends(catalog, make_char):
    hero = make_char("krieger")
    enemies = foes(catalog, hp=999, defense=99, attack=-50)
    result = resolve_fight(catalog, random.Random(1), [hero], {hero.id: Tactic("untaetig")}, enemies)
    assert result.outcome == "offen"
    assert result.rounds == catalog.rules.combat_rounds_per_turn
    attacks = [e for e in result.events if e.kind == "gegnerangriff"]
    assert attacks and all(e.roll.advantage == "nachteil" for e in attacks)
    assert not [e for e in result.events if e.kind == "angriff"]


def test_alone_at_zero_hp_means_death(catalog, make_char):
    hero = make_char("magier")
    enemies = foes(catalog, n=3, hp=999, defense=99, attack=99, damage="2d6")
    result = resolve_fight(catalog, random.Random(3), [hero], {}, enemies)
    assert result.outcome == "verloren"
    assert result.died == [hero.id]
    assert hero.down and hero.hp == 0


def test_down_not_dead_when_the_group_wins(catalog, make_char):
    tank = make_char("krieger", id="tank")
    mage = make_char("magier", id="mage")
    mage.hp, mage.down = 0, True
    enemies = foes(catalog, hp=1, defense=1, attack=-50)
    result = resolve_fight(catalog, random.Random(2), [tank, mage], attack(tank), enemies)
    assert result.outcome == "gewonnen"
    assert not mage.down and mage.hp == 1
    assert result.died == []


def test_rauchbombe_escapes_before_the_fight(catalog, make_char):
    rogue = make_char("schurke")
    rogue.abilities.append("rauchbombe")
    enemies = foes(catalog, tier="boss", attack=99)
    result = resolve_fight(catalog, random.Random(1), [rogue],
                           {rogue.id: Tactic("faehigkeit", ability="rauchbombe")}, enemies)
    assert result.outcome == "entkommen"
    assert result.escaped == [rogue.id]
    assert result.participants == []
    assert rogue.cooldowns["rauchbombe"] == catalog.rules.ability_cooldown_turns


def test_bannkreis_drives_off_weak_and_normal_enemies(catalog, make_char):
    cleric = make_char("kleriker")
    cleric.abilities.append("bannkreis")
    enemies = foes(catalog, n=2, attack=-50) + build_enemies(catalog, [EnemySpec("Oger", "stark")], 1, 1)
    resolve_fight(catalog, random.Random(1), [cleric], {cleric.id: Tactic("faehigkeit", ability="bannkreis")}, enemies)
    assert all(e.fled for e in enemies if e.tier == "normal")
    assert not enemies[-1].fled


def test_ability_on_cooldown_falls_back_to_attack(catalog, make_char):
    hero = make_char("krieger")
    hero.cooldowns["wuchtschlag"] = 2
    enemies = foes(catalog, hp=999, attack=-50)
    result = resolve_fight(catalog, random.Random(1), [hero], {hero.id: Tactic("faehigkeit", ability="wuchtschlag")}, enemies)
    assert result.events[0].kind == "faehigkeit_nicht_bereit"
    assert any(e.kind == "angriff" for e in result.events)


def test_wuchtschlag_hits_for_sure_with_double_damage(catalog, make_char):
    hero = make_char("krieger", element="stahl")
    enemies = foes(catalog, hp=999, defense=99, attack=-50)
    result = resolve_fight(catalog, random.Random(1), [hero], {hero.id: Tactic("faehigkeit", ability="wuchtschlag")}, enemies)
    first = next(e for e in result.events if e.kind == "angriff")
    assert first.hit and first.note == "wuchtschlag"
    assert first.damage >= 2 * (1 + 3)


def test_unerschuetterlich_keeps_krieger_at_one_hp_and_draws_attacks(catalog, make_char):
    tank = make_char("krieger", id="tank")
    tank.abilities.append("unerschuetterlich")
    mage = make_char("magier", id="mage")
    enemies = foes(catalog, n=3, hp=999, defense=99, attack=99, damage="2d6")
    resolve_fight(catalog, random.Random(5), [tank, mage],
                  {tank.id: Tactic("faehigkeit", ability="unerschuetterlich")}, enemies)
    assert tank.hp == 1 and not tank.down
    assert mage.hp == ch.max_hp(catalog, mage)


def test_elementarbarriere_halves_damage(catalog, make_char):
    mage = make_char("magier", element="stahl")
    mage.abilities.append("elementarbarriere")
    mage.hp = 999
    enemies = foes(catalog, hp=999, defense=99, attack=99, damage="1d1")
    result = resolve_fight(catalog, random.Random(1), [mage],
                           {mage.id: Tactic("faehigkeit", ability="elementarbarriere")}, enemies)
    hits = [e for e in result.events if e.kind == "gegnerangriff" and e.hit and not e.critical]
    assert hits and all(e.damage == 1 for e in hits)


def test_strong_element_gives_advantage(catalog, make_char):
    mage = make_char("magier", element="wasser")
    enemies = foes(catalog, elements=["feuer"], hp=999, attack=-50)
    result = resolve_fight(catalog, random.Random(1), [mage], attack(mage), enemies)
    attacks = [e for e in result.events if e.kind == "angriff"]
    assert attacks and all(e.matchup == "stark" and e.roll.advantage == "vorteil" for e in attacks)


def test_successful_flight(catalog, make_char):
    rogue = make_char("schurke")
    # find a seed where the Geschick check succeeds
    for seed in range(50):
        rogue.hp, rogue.down = 10, False
        result = resolve_fight(catalog, random.Random(seed), [rogue], {rogue.id: Tactic("fliehen")}, foes(catalog, hp=999, attack=99))
        if result.escaped:
            break
    assert result.outcome == "entkommen"
    assert result.participants == []


def test_potion_heals_and_is_used_up(catalog, make_char):
    hero = make_char("krieger")
    hero.hp = 2
    potion = next(i for i in hero.bag if i.base == "heiltrank")
    enemies = foes(catalog, hp=999, defense=99, attack=-50)
    resolve_fight(catalog, random.Random(1), [hero], {hero.id: Tactic("gegenstand", item_id=potion.id)}, enemies)
    assert hero.hp == 2 + 7
    assert all(i.base != "heiltrank" for i in hero.bag)


def test_fight_continues_next_turn_with_same_enemies(catalog, make_char):
    hero = make_char("krieger")
    enemies = foes(catalog, hp=60, defense=1, attack=-50)
    first = resolve_fight(catalog, random.Random(1), [hero], attack(hero), enemies)
    assert first.outcome == "offen"
    hp_after_first = enemies[0].hp
    assert hp_after_first < 60
    resolve_fight(catalog, random.Random(2), [hero], attack(hero), enemies)
    assert enemies[0].hp < hp_after_first
