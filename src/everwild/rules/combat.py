"""Fights: up to 3 rounds per turn, simulated by Python (design §7).

``resolve_fight`` changes the characters (HP, down, cooldowns, used items)
and the enemies (HP, fled) in place and returns everything that happened as
events, which feed the result box and the narrator.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Literal

from ..catalog import Catalog
from ..models import Character, Element
from . import character as ch
from . import elements as el
from .dice import Advantage, D20Roll, check, combine_advantage, roll_d20, roll_dice
from .enemies import Enemy
from .items import ItemError, find_in_bag, remove_from_bag

TacticKind = Literal["angriff", "faehigkeit", "verteidigen", "gegenstand", "fliehen", "untaetig"]
FightOutcome = Literal["gewonnen", "verloren", "entkommen", "offen"]

# abilities that act before the first round or change the whole fight
_GROUP_ABILITIES = {"schlachtruf", "heldenlied", "spottlied", "elementarbarriere", "unerschuetterlich", "schutzsegen"}


@dataclass
class Tactic:
    """A player's action for the whole fight (§7).

    ``target`` is an enemy id for attacks, or an ally id for defending,
    healing and items. ``item_id`` names the item for ``gegenstand``.
    """

    kind: TacticKind = "angriff"
    target: str | None = None
    ability: str | None = None
    item_id: str | None = None


@dataclass
class CombatEvent:
    round: int
    actor: str
    kind: str
    target: str | None = None
    roll: D20Roll | None = None
    total: int | None = None
    target_number: int | None = None
    hit: bool | None = None
    critical: bool = False
    damage: int = 0
    healed: int = 0
    matchup: str = "neutral"
    note: str = ""


@dataclass
class FightResult:
    outcome: FightOutcome
    rounds: int
    events: list[CombatEvent]
    defeated: list[Enemy]
    escaped: list[str] = field(default_factory=list)
    died: list[str] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)


@dataclass
class _State:
    catalog: Catalog
    rng: random.Random
    players: list[Character]
    enemies: list[Enemy]
    tactics: dict[str, Tactic]
    events: list[CombatEvent] = field(default_factory=list)
    escaped: set[str] = field(default_factory=set)
    defending: set[str] = field(default_factory=set)
    floor_one: set[str] = field(default_factory=set)
    taunt: str | None = None
    players_advantage: bool = False
    enemies_disadvantage: bool = False
    half_damage: bool = False
    whirlwind: set[str] = field(default_factory=set)
    weapon_coat: dict[str, Element] = field(default_factory=dict)
    round: int = 0

    def standing(self) -> list[Character]:
        return [p for p in self.players if not p.down and p.id not in self.escaped]

    def alive_enemies(self) -> list[Enemy]:
        return [e for e in self.enemies if e.alive]

    def player(self, player_id: str | None) -> Character | None:
        return next((p for p in self.players if p.id == player_id), None)

    def log(self, **kwargs) -> CombatEvent:
        event = CombatEvent(round=self.round, **kwargs)
        self.events.append(event)
        return event


def resolve_fight(
    catalog: Catalog,
    rng: random.Random,
    players: list[Character],
    tactics: dict[str, Tactic],
    enemies: list[Enemy],
) -> FightResult:
    state = _State(catalog, rng, players, enemies, {p.id: tactics.get(p.id, Tactic("untaetig")) for p in players})
    participants = [p.id for p in players]

    _prepare(state)
    if state.escaped and len(state.escaped) == len(players):
        return _finish(state, "entkommen", participants)

    for number in range(1, catalog.rules.combat_rounds_per_turn + 1):
        state.round = number
        for player in list(state.players):
            if player.down or player.id in state.escaped or not state.alive_enemies():
                continue
            _player_turn(state, player)
        if not state.alive_enemies():
            return _finish(state, "gewonnen", participants)
        for enemy in state.alive_enemies():
            for _ in range(enemy.attacks):
                if not state.standing():
                    break
                _enemy_attack(state, enemy, state.rng)
        if not state.standing():
            return _finish(state, "entkommen" if not _down_left(state) else "verloren", participants)

    return _finish(state, "offen", participants)


# --- setup -------------------------------------------------------------------


def _ability_usable(state: _State, player: Character, ability: str | None) -> bool:
    if ability is None or ability not in state.catalog.abilities:
        return False
    return state.catalog.abilities[ability].combat and ch.ability_ready(player, ability)


def _prepare(state: _State) -> None:
    """Applies everything that happens before round 1."""
    state.round = 0
    surprise: list[Character] = []
    for player in state.players:
        tactic = state.tactics[player.id]
        if tactic.kind == "verteidigen":
            state.defending.add(player.id)
            if tactic.target:
                state.defending.add(tactic.target)
        elif tactic.kind == "untaetig":
            state.defending.add(player.id)

        if tactic.kind != "faehigkeit" or player.down:
            continue
        ability = tactic.ability
        if not _ability_usable(state, player, ability):
            name = state.catalog.abilities[ability].name if ability in state.catalog.abilities else str(ability)
            state.log(actor=player.id, kind="faehigkeit_nicht_bereit", note=name)
            tactic.kind = "angriff"
            continue
        ch.use_ability(state.catalog, player, ability)

        if ability == "rauchbombe":
            state.log(actor=player.id, kind="faehigkeit", note="rauchbombe")
            state.escaped = {p.id for p in state.players}
            for p in state.players:
                if p.down:
                    p.down, p.hp = False, max(p.hp, 1)
            return
        if ability == "bannkreis":
            fled = [e for e in state.alive_enemies() if e.tier in ("schwach", "normal")]
            for enemy in fled:
                enemy.fled = True
            state.log(actor=player.id, kind="faehigkeit", note=f"bannkreis:{len(fled)}")
        elif ability == "schlachtruf" or ability == "heldenlied":
            state.players_advantage = True
            state.log(actor=player.id, kind="faehigkeit", note=ability)
        elif ability == "spottlied":
            state.enemies_disadvantage = True
            state.log(actor=player.id, kind="faehigkeit", note=ability)
        elif ability == "elementarbarriere":
            state.half_damage = True
            state.log(actor=player.id, kind="faehigkeit", note=ability)
        elif ability == "unerschuetterlich":
            state.taunt = player.id
            state.floor_one.add(player.id)
            state.log(actor=player.id, kind="faehigkeit", note=ability)
        elif ability == "schutzsegen":
            target = state.player(tactic.target) or player
            state.floor_one.add(target.id)
            state.log(actor=player.id, kind="faehigkeit", target=target.id, note=ability)
        elif ability == "wirbelwind":
            state.whirlwind.add(player.id)
            state.log(actor=player.id, kind="faehigkeit", note=ability)
        elif ability == "hinterhalt":
            state.log(actor=player.id, kind="faehigkeit", note=ability)
            surprise = [p for p in state.players if not p.down]
        elif ability == "gezielter_schuss":
            target = _pick_target(state, tactic.target)
            if target is not None:
                _attack(state, player, target, advantage="vorteil", damage_factor=2, note="gezielter_schuss")
        if ability in _GROUP_ABILITIES or ability in ("bannkreis", "wirbelwind", "hinterhalt", "gezielter_schuss"):
            tactic.ability = None  # already done; the player attacks from round 1 on
            tactic.kind = "angriff"

    for player in surprise:
        target = _pick_target(state, state.tactics[player.id].target)
        if target is not None:
            _attack(state, player, target, note="hinterhalt")


# --- player actions ----------------------------------------------------------


def _pick_target(state: _State, wanted: str | None) -> Enemy | None:
    alive = state.alive_enemies()
    if not alive:
        return None
    chosen = next((e for e in alive if e.id == wanted), None)
    return chosen or min(alive, key=lambda e: (e.hp, e.id))


def _player_turn(state: _State, player: Character) -> None:
    tactic = state.tactics[player.id]
    first = state.round == 1

    if player.id in state.whirlwind:
        for enemy in state.alive_enemies():
            _attack(state, player, enemy, note="wirbelwind")
        return

    if tactic.kind == "fliehen":
        if first:
            _flee(state, player)
        return
    if tactic.kind in ("verteidigen", "untaetig"):
        return
    if tactic.kind == "gegenstand":
        if first:
            _use_item(state, player, tactic)
        state.defending.add(player.id)
        return
    if tactic.kind == "faehigkeit" and first and tactic.ability:
        if _use_ability(state, player, tactic):
            return
    target = _pick_target(state, tactic.target)
    if target is not None:
        _attack(state, player, target)


def _use_ability(state: _State, player: Character, tactic: Tactic) -> bool:
    """Round-1 abilities that replace the normal attack. Returns True if one was used."""
    catalog, ability = state.catalog, tactic.ability
    tactic.kind = "angriff"  # from round 2 on: attack normally
    if ability in ("wuchtschlag", "schattenschritt"):
        target = _pick_target(state, tactic.target)
        if target is not None:
            _attack(state, player, target, auto_hit=True, damage_factor=2, note=ability)
        return True
    if ability == "feuerball":
        verstand = ch.attribute(catalog, player, "verstand")
        for enemy in state.alive_enemies():
            _area_damage(state, player, enemy, "1d6", verstand, player.element, ability)
        return True
    if ability == "pfeilhagel":
        for enemy in state.alive_enemies():
            _attack(state, player, enemy, note=ability)
        return True
    if ability == "heilung":
        target = state.player(tactic.target) or player
        amount = sum(roll_dice(state.rng, "2d6")) + ch.attribute(catalog, player, "verstand")
        healed = ch.heal(catalog, target, amount)
        state.log(actor=player.id, kind="heilung", target=target.id, healed=healed, note=ability)
        return True
    if ability == "gruppenheilung":
        for ally in state.players:
            if ally.id in state.escaped:
                continue
            healed = ch.heal(catalog, ally, ch.max_hp(catalog, ally) // 2)
            state.log(actor=player.id, kind="heilung", target=ally.id, healed=healed, note=ability)
        return True
    return False


def _use_item(state: _State, player: Character, tactic: Tactic) -> None:
    catalog = state.catalog
    try:
        item = find_in_bag(player, tactic.item_id or "")
    except ItemError:
        state.log(actor=player.id, kind="gegenstand_fehlt")
        return
    effect = catalog.items[item.base].effect
    allowed = catalog.items[item.base].classes
    if allowed is not None and player.class_id not in allowed:
        state.log(actor=player.id, kind="gegenstand_unbrauchbar", note=item.name)
        return
    if effect == "heal_half":
        target = state.player(tactic.target) or player
        amount = int(ch.max_hp(catalog, target) * catalog.rules.potion_heal_fraction)
        healed = ch.heal(catalog, target, amount)
        state.log(actor=player.id, kind="heilung", target=target.id, healed=healed, note=item.name)
    elif effect == "spell_all":
        dice = catalog.items[item.base].damage or "2d6"
        for enemy in state.alive_enemies():
            _area_damage(state, player, enemy, dice, 0, item.element, item.name)
    elif effect == "coat_weapon":
        state.weapon_coat[player.id] = item.element
        state.log(actor=player.id, kind="waffe_beschichtet", note=item.element)
    else:
        state.log(actor=player.id, kind="gegenstand_unbrauchbar", note=item.name)
        return
    remove_from_bag(player, item.id, 1)


def _flee(state: _State, player: Character) -> None:
    catalog = state.catalog
    target = catalog.rules.difficulties[catalog.rules.flee_difficulty]
    result = check(state.rng, ch.attribute(catalog, player, "geschick"), target,
                   complication_margin=0)
    state.log(actor=player.id, kind="flucht", roll=result.roll, total=result.total,
              target_number=target, hit=result.succeeded)
    if result.succeeded:
        state.escaped.add(player.id)
        return
    state.defending.add(player.id)
    for enemy in state.alive_enemies():
        if player.down:
            break
        _enemy_attack(state, enemy, state.rng, forced_target=player)


def _attack(
    state: _State,
    player: Character,
    enemy: Enemy,
    *,
    auto_hit: bool = False,
    advantage: Advantage = "normal",
    damage_factor: int = 1,
    note: str = "",
) -> None:
    catalog = state.catalog
    profile = ch.attack_profile(catalog, player, state.weapon_coat.get(player.id))
    result = el.matchup(catalog, profile.element, enemy.elements)
    adv = combine_advantage(
        advantage,
        "vorteil" if state.players_advantage else "normal",
        "vorteil" if result == "stark" else "normal",
    )
    roll = roll_d20(state.rng, adv)
    total = roll.kept + profile.attack_bonus
    critical = roll.natural_20
    hit = auto_hit or critical or (not roll.natural_1 and total >= enemy.defense)
    event = state.log(actor=player.id, kind="angriff", target=enemy.id, roll=None if auto_hit else roll,
                      total=None if auto_hit else total, target_number=enemy.defense, hit=hit,
                      critical=critical and not auto_hit, matchup=result, note=note)
    if not hit:
        return
    dice = roll_dice(state.rng, profile.dice)
    if critical:
        dice += roll_dice(state.rng, profile.dice)
    raw = (sum(dice) + profile.damage_bonus) * damage_factor
    event.damage = _hurt_enemy(state, enemy, el.apply_multiplier(raw, el.damage_multiplier(catalog, result)))


def _area_damage(state: _State, player: Character, enemy: Enemy, dice: str, bonus: int,
                 element: Element, note: str) -> None:
    catalog = state.catalog
    result = el.matchup(catalog, element, enemy.elements)
    raw = sum(roll_dice(state.rng, dice)) + bonus
    damage = el.apply_multiplier(raw, el.damage_multiplier(catalog, result))
    event = state.log(actor=player.id, kind="angriff", target=enemy.id, hit=True, matchup=result, note=note)
    event.damage = _hurt_enemy(state, enemy, damage)


def _hurt_enemy(state: _State, enemy: Enemy, damage: int) -> int:
    dealt = min(enemy.hp, damage)
    enemy.hp -= dealt
    if enemy.hp <= 0:
        state.log(actor=enemy.id, kind="gegner_besiegt")
    return damage


# --- enemy actions -----------------------------------------------------------


def _enemy_attack(state: _State, enemy: Enemy, rng: random.Random, forced_target: Character | None = None) -> None:
    catalog = state.catalog
    standing = state.standing()
    if forced_target is not None:
        target = forced_target
    elif state.taunt and (taunter := state.player(state.taunt)) in standing:
        target = taunter
    else:
        target = rng.choice(standing)

    adv = combine_advantage(
        "nachteil" if state.enemies_disadvantage else "normal",
        "nachteil" if target.id in state.defending else "normal",
    )
    roll = roll_d20(rng, adv)
    total = roll.kept + enemy.attack
    armor = ch.armor_value(catalog, target)
    critical = roll.natural_20
    hit = critical or (not roll.natural_1 and total >= armor)
    event = state.log(actor=enemy.id, kind="gegnerangriff", target=target.id, roll=roll, total=total,
                      target_number=armor, hit=hit, critical=critical)
    if not hit:
        return
    dice = roll_dice(rng, enemy.damage)
    if critical:
        dice += roll_dice(rng, enemy.damage)
    damage = sum(dice) + enemy.damage_bonus
    if el.resists(catalog, target, enemy.attack_element):
        damage = el.apply_multiplier(damage, 0.5)
    if state.half_damage:
        damage = el.apply_multiplier(damage, 0.5)
    event.damage = damage
    floor = 1 if target.id in state.floor_one else 0
    target.hp = max(floor, target.hp - damage)
    if target.hp <= 0:
        target.hp = 0
        target.down = True
        state.log(actor=target.id, kind="kampfunfaehig")


# --- end of fight ------------------------------------------------------------


def _down_left(state: _State) -> list[Character]:
    return [p for p in state.players if p.down and p.id not in state.escaped]


def _finish(state: _State, outcome: FightOutcome, participants: list[str]) -> FightResult:
    died: list[str] = []
    if outcome in ("gewonnen", "entkommen"):
        for player in state.players:
            if player.down:
                player.down = False
                player.hp = max(player.hp, 1)
                state.log(actor=player.id, kind="erwacht")
    elif outcome == "verloren":
        died = [p.id for p in _down_left(state)]
    return FightResult(
        outcome=outcome,
        rounds=state.round,
        events=state.events,
        defeated=[e for e in state.enemies if not e.alive],
        escaped=sorted(state.escaped),
        died=died,
        participants=[pid for pid in participants if pid not in state.escaped],
    )
