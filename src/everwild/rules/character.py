"""Character creation, derived stats, abilities, XP and levels (design §4, §9)."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..catalog import Catalog
from ..models import Attribute, Character, Element, Item
from . import elements as el
from .dice import parse_dice
from .items import add_to_bag, make_item


class CharacterError(Exception):
    """A rule forbids the change. The message is player-facing German."""


# --- creation ----------------------------------------------------------------


def create_character(
    catalog: Catalog,
    rng: random.Random,
    *,
    id: str,
    name: str,
    class_id: str,
    element: Element,
    background: str = "",
    class_label: str | None = None,
    location: str = "",
    turn: int = 0,
) -> Character:
    if class_id not in catalog.classes:
        raise CharacterError(f"Unbekannte Klasse: {class_id}")
    cls = catalog.classes[class_id]
    character = Character(
        id=id,
        name=name,
        class_id=class_id,
        class_label=class_label or cls.label,
        element=element,
        background=background,
        joined_turn=turn,
        hp=cls.hp,
        affinity={element: 1} if element != "stahl" else {},
        abilities=[cls.first_ability] if cls.first_ability else [],
        gold=catalog.rules.starting_gold,
        location=location,
        last_rest_point=location,
    )
    _give_starting_gear(catalog, rng, character)
    return character


def _give_starting_gear(catalog: Catalog, rng: random.Random, character: Character) -> None:
    gear = catalog.classes[character.class_id].starting_gear
    character.equipment.waffe = make_item(catalog, rng, gear.waffe, name=catalog.items[gear.waffe].name)
    character.equipment.ruestung = make_item(catalog, rng, gear.ruestung, name=catalog.items[gear.ruestung].name)
    if gear.schild:
        character.equipment.schild = make_item(catalog, rng, gear.schild, name=catalog.items[gear.schild].name)
    for base in gear.bag:
        element = character.element if base == "schriftrolle" else "stahl"
        name = catalog.items[base].name
        if element != "stahl":
            name = f"{name} ({catalog.rules.elements[element].label})"
        add_to_bag(catalog, character, make_item(catalog, rng, base, element=element, name=name))
    add_to_bag(catalog, character, make_item(catalog, rng, "heiltrank", name="Heiltrank"))


def change_class(
    catalog: Catalog,
    rng: random.Random,
    character: Character,
    class_id: str,
    *,
    element: Element | None = None,
    class_label: str | None = None,
    turn: int,
    length: str,
) -> Character:
    """Free class (and element) change during the first turns (design §14)."""
    if turn - character.joined_turn >= catalog.rules.free_change_turns:
        raise CharacterError("Die Klasse kann nur in den ersten Runden gewechselt werden.")
    old_gear = set(catalog.classes[character.class_id].starting_gear.bag) | {"heiltrank"}
    found = [item for item in character.bag if item.base not in old_gear]
    fresh = create_character(
        catalog, rng,
        id=character.id, name=character.name, class_id=class_id,
        element=element or character.element, background=character.background,
        class_label=class_label, location=character.location, turn=character.joined_turn,
    )
    fresh.last_rest_point = character.last_rest_point
    fresh.gold = character.gold
    for item in found:
        add_to_bag(catalog, fresh, item)
    set_xp(catalog, fresh, character.xp, length)
    fresh.hp = max_hp(catalog, fresh)
    return fresh


# --- derived stats -----------------------------------------------------------


def attribute(catalog: Catalog, character: Character, name: Attribute) -> int:
    base = catalog.classes[character.class_id].attributes[name]
    value = base + character.attribute_increases.count(name)
    return min(value, catalog.rules.max_attribute)


def max_hp(catalog: Catalog, character: Character) -> int:
    cls = catalog.classes[character.class_id]
    return cls.hp + cls.hp_per_level * (character.level - 1)


def armor_value(catalog: Catalog, character: Character) -> int:
    rules = catalog.rules
    value = rules.base_armor_value + catalog.classes[character.class_id].armor_bonus
    armor = character.equipment.ruestung
    if armor is not None:
        value += catalog.items[armor.base].armor + rules.rarities[armor.rarity].bonus
    shield = character.equipment.schild
    if shield is not None:
        value += rules.shield_bonus + rules.rarities[shield.rarity].bonus
    return value


@dataclass(frozen=True)
class AttackProfile:
    """Everything needed to roll one attack."""

    name: str
    dice: str
    attribute: Attribute
    attack_bonus: int
    damage_bonus: int
    element: Element
    ranged: bool
    spell: bool

    @property
    def damage_label(self) -> str:
        count, sides = parse_dice(self.dice)
        dice = f"d{sides}" if count == 1 else f"{count}d{sides}"
        return f"{dice} + {self.damage_bonus}" if self.damage_bonus else dice


def spell_dice(catalog: Catalog, character: Character) -> str | None:
    spell = catalog.classes[character.class_id].basic_spell
    if spell is None:
        return None
    dice = spell.dice_by_level[1]
    for level, value in sorted(spell.dice_by_level.items()):
        if character.level >= level:
            dice = value
    return dice


def attack_profile(catalog: Catalog, character: Character, element_override: Element | None = None) -> AttackProfile:
    """The character's normal attack: the weapon, or the Magier's Arkaner Blitz."""
    rules = catalog.rules
    weapon = character.equipment.waffe
    cls = catalog.classes[character.class_id]

    if cls.basic_spell is not None:
        verstand = attribute(catalog, character, "verstand")
        bonus = 0
        if weapon is not None:
            bonus = catalog.items[weapon.base].spell_bonus + rules.rarities[weapon.rarity].bonus
        spell_element = element_override or character.element
        affinity = el.effective_affinity(catalog, character, spell_element)
        return AttackProfile(
            name=cls.basic_spell.name,
            dice=spell_dice(catalog, character) or "1d6",
            attribute="verstand",
            attack_bonus=verstand + affinity,
            damage_bonus=verstand + bonus,
            element=spell_element,
            ranged=True,
            spell=True,
        )

    if weapon is None:
        value = attribute(catalog, character, "staerke")
        return AttackProfile("Fäuste", "1d2", "staerke", value, value, element_override or "stahl", False, False)

    base = catalog.items[weapon.base]
    allowed = list(base.attributes or ["staerke"]) + ([] if base.ranged else cls.weapon_attributes)
    attr = max(allowed, key=lambda a: attribute(catalog, character, a))
    value = attribute(catalog, character, attr)
    rarity_bonus = rules.rarities[weapon.rarity].bonus
    weapon_element = element_override or weapon.element
    affinity = el.effective_affinity(catalog, character, weapon_element)
    return AttackProfile(
        name=weapon.name,
        dice=base.damage or "1d4",
        attribute=attr,
        attack_bonus=value + rarity_bonus + affinity,
        damage_bonus=value + rarity_bonus,
        element=weapon_element,
        ranged=base.ranged,
        spell=False,
    )


# --- abilities ---------------------------------------------------------------


def ability_ready(character: Character, ability: str) -> bool:
    return ability in character.abilities and character.cooldowns.get(ability, 0) == 0


def use_ability(catalog: Catalog, character: Character, ability: str) -> None:
    if ability not in character.abilities:
        raise CharacterError(f"{character.name} beherrscht {ability} nicht.")
    if not ability_ready(character, ability):
        raise CharacterError(f"{catalog.abilities[ability].name} ist noch nicht bereit.")
    character.cooldowns[ability] = catalog.rules.ability_cooldown_turns


def tick_cooldowns(character: Character) -> None:
    """Called at the start of every turn. An ability used on turn T is ready on turn T + 3."""
    character.cooldowns = {k: v - 1 for k, v in character.cooldowns.items() if v > 1}


def choose_second_ability(catalog: Catalog, character: Character, ability: str) -> None:
    """Stores the choice; it takes effect at the second-ability level."""
    if ability not in catalog.classes[character.class_id].second_abilities:
        raise CharacterError(f"{ability} ist keine Wahl für {character.class_label}.")
    if any(a in catalog.classes[character.class_id].second_abilities for a in character.abilities):
        raise CharacterError("Die zweite Fähigkeit wurde schon gewählt.")
    character.ability_choice = ability
    if character.level >= catalog.rules.second_ability_level:
        _grant_second_ability(catalog, character)


def _grant_second_ability(catalog: Catalog, character: Character) -> str | None:
    if character.ability_choice is None:
        return None
    character.abilities.append(character.ability_choice)
    granted = character.ability_choice
    character.ability_choice = None
    character.ability_offer_turn = None
    return granted


def resolve_pending_ability(catalog: Catalog, rng: random.Random, character: Character, turn: int) -> str | None:
    """If the offer from the last turn wasn't answered, picks one at random (§9)."""
    if character.ability_offer_turn is None or turn <= character.ability_offer_turn:
        return None
    if character.ability_choice is None:
        character.ability_choice = rng.choice(catalog.classes[character.class_id].second_abilities)
    return _grant_second_ability(catalog, character)


# --- XP and levels -----------------------------------------------------------


@dataclass
class LevelUp:
    level: int
    hp_gained: int
    attribute: Attribute | None = None
    ability_granted: str | None = None
    ability_offered: list[str] = field(default_factory=list)


def level_for_xp(catalog: Catalog, xp: int, length: str) -> int:
    per_level = catalog.rules.game_lengths[length].xp_per_level
    return min(catalog.rules.max_level, 1 + xp // per_level)


def level_start_xp(catalog: Catalog, level: int, length: str) -> int:
    return (level - 1) * catalog.rules.game_lengths[length].xp_per_level


def xp_for_next_level(catalog: Catalog, character: Character, length: str) -> int | None:
    if character.level >= catalog.rules.max_level:
        return None
    return level_start_xp(catalog, character.level + 1, length)


def add_xp(
    catalog: Catalog,
    character: Character,
    amount: int,
    length: str,
    *,
    average_level: float | None = None,
    turn: int = 0,
) -> tuple[int, list[LevelUp]]:
    """Adds XP (with the catch-up bonus) and applies level-ups.

    Returns the XP actually gained and one entry per new level.
    """
    if average_level is not None and character.level < average_level:
        amount = int(amount * catalog.rules.xp.catch_up_multiplier)
    character.xp += amount
    return amount, _apply_levels(catalog, character, length, turn)


def set_xp(catalog: Catalog, character: Character, xp: int, length: str, turn: int = 0) -> list[LevelUp]:
    character.xp = xp
    return _apply_levels(catalog, character, length, turn)


def _apply_levels(catalog: Catalog, character: Character, length: str, turn: int) -> list[LevelUp]:
    rules = catalog.rules
    cls = catalog.classes[character.class_id]
    target = level_for_xp(catalog, character.xp, length)
    events: list[LevelUp] = []
    while character.level < target:
        character.level += 1
        event = LevelUp(level=character.level, hp_gained=cls.hp_per_level)
        character.hp += cls.hp_per_level
        if character.level in rules.attribute_increase_levels:
            event.attribute = _raise_attribute(catalog, character)
        if character.level == rules.second_ability_level and cls.second_abilities:
            if character.ability_choice is not None:
                event.ability_granted = _grant_second_ability(catalog, character)
            else:
                character.ability_offer_turn = turn
                event.ability_offered = list(cls.second_abilities)
        events.append(event)
    return events


def _raise_attribute(catalog: Catalog, character: Character) -> Attribute | None:
    candidates: list[Attribute] = []
    if character.attribute_choice is not None:
        candidates.append(character.attribute_choice)
    main = catalog.classes[character.class_id].main_attribute
    candidates += [main, "staerke", "geschick", "verstand"]
    character.attribute_choice = None
    for name in candidates:
        if attribute(catalog, character, name) < catalog.rules.max_attribute:
            character.attribute_increases.append(name)
            return name
    return None


# --- healing -----------------------------------------------------------------


def heal(catalog: Catalog, character: Character, amount: int) -> int:
    """Heals and wakes a down character. Returns the HP actually restored."""
    before = character.hp
    character.hp = min(max_hp(catalog, character), character.hp + max(0, amount))
    if character.hp > 0:
        character.down = False
    return character.hp - before


def all_items(character: Character) -> list[Item]:
    equipped = [i for i in vars(character.equipment).values() if i is not None]
    return equipped + list(character.bag)
