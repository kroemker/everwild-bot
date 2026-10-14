"""Pydantic models for the hand-written catalog and for the game state.

Catalog models mirror the JSON files in ``catalog/``. State models are what
the bot writes to ``game/`` (characters, items, graves).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Attribute = Literal["staerke", "geschick", "verstand"]
Element = Literal["feuer", "wasser", "erde", "luft", "licht", "schatten", "stahl"]
Rarity = Literal["gewoehnlich", "selten", "legendaer"]
Tier = Literal["schwach", "normal", "stark", "elite", "boss"]
Category = Literal[
    "waffe", "schild", "ruestung", "talisman",
    "verbrauchsgut", "werkzeug", "wertsache", "questgegenstand",
]
Gender = Literal["m", "f", "n", "pl"]
Slot = Literal["waffe", "schild", "ruestung", "talisman"]

ATTRIBUTE_LABELS: dict[str, str] = {"staerke": "STÄ", "geschick": "GES", "verstand": "VER"}


# --- catalog -----------------------------------------------------------------


class GameLength(BaseModel):
    label: str
    target_turns: int
    xp_per_level: int
    regions: int
    shards_needed: int


class XpRules(BaseModel):
    enemy: dict[Tier, int]
    side_quest: int
    main_quest_step: int
    new_location: int
    check: dict[str, int]
    catch_up_multiplier: float


class RarityDef(BaseModel):
    label: str
    marker: str
    bonus: int
    price_multiplier: int


class ElementDef(BaseModel):
    label: str
    emoji: str
    opposite: Element | None


class Rules(BaseModel):
    difficulties: dict[str, int]
    complication_margin: int
    ability_cooldown_turns: int
    second_ability_level: int
    max_level: int
    max_attribute: int
    attribute_increase_levels: list[int]
    bag_slots: int
    stack_size: int
    base_armor_value: int
    shield_bonus: int
    combat_rounds_per_turn: int
    flee_difficulty: str
    potion_heal_fraction: float
    rest_heal_fraction: float
    camp_after_idle_turns: int
    free_change_turns: int
    max_players: int
    starting_gold: int
    sell_price_fraction: float
    game_lengths: dict[str, GameLength]
    xp: XpRules
    rarities: dict[Rarity, RarityDef]
    elements: dict[Element, ElementDef]
    element_strong_multiplier: float
    element_weak_multiplier: float
    affinity_max: int
    affinity_resist_from: int
    max_affinity_elements: int


class BasicSpell(BaseModel):
    name: str
    dice_by_level: dict[int, str]


class StartingGear(BaseModel):
    waffe: str
    schild: str | None = None
    ruestung: str
    bag: list[str] = Field(default_factory=list)


class ClassDef(BaseModel):
    label: str
    label_f: str
    attributes: dict[Attribute, int]
    main_attribute: Attribute
    hp: int
    hp_per_level: int
    armor_bonus: int
    # extra attributes this class may use for weapon attacks (e.g. Kleriker: Verstand)
    weapon_attributes: list[Attribute] = Field(default_factory=list)
    passive: str
    first_ability: str | None
    second_abilities: list[str]
    basic_spell: BasicSpell | None = None
    selectable: bool = True
    starting_gear: StartingGear


class AbilityDef(BaseModel):
    name: str
    text: str
    combat: bool
    class_: str = Field(alias="class")


class ItemBase(BaseModel):
    name: str
    category: Category
    gender: Gender
    price: int
    damage: str | None = None
    attributes: list[Attribute] = Field(default_factory=list)
    ranged: bool = False
    two_handed: bool = False
    spell_bonus: int = 0
    armor: int = 0
    classes: list[str] | None = None
    effect: str | None = None
    variants: list[str] = Field(default_factory=list)
    heads: list[str] = Field(default_factory=list)


class ElementWords(BaseModel):
    prefixes: list[str]
    adjectives: list[str]
    genitives: list[str]


class NameLists(BaseModel):
    common_adjectives: list[str]
    quality_prefixes: list[str]
    quality_genitives: list[str]
    elements: dict[Element, ElementWords]


class TierDef(BaseModel):
    label: str
    hp: int
    defense: int
    attack: int
    damage: str
    hp_per_player: bool = False
    # bosses fight several heroes at once: extra attacks per round per extra player
    extra_attacks_per_player: float = 0.0
    # overrides the general region HP scaling for this tier (bosses grow faster)
    hp_per_level: float | None = None


class RegionScaling(BaseModel):
    hp_per_level: float
    defense_every_levels: int
    attack_every_levels: int
    damage_every_levels: int


class GroupScaling(BaseModel):
    extra_per_player: float


class LootTier(BaseModel):
    gold: str
    item_chance: float
    rare_chance: float


class LootTable(BaseModel):
    tiers: dict[Tier, LootTier]
    item_pool: list[str]
    region_element_chance: float


class EnemyCatalog(BaseModel):
    tiers: dict[Tier, TierDef]
    region_scaling: RegionScaling
    group_scaling: GroupScaling


# --- game state --------------------------------------------------------------


class Item(BaseModel):
    """One item (or stack) owned by a character or lying somewhere."""

    id: str
    base: str
    name: str
    rarity: Rarity = "gewoehnlich"
    element: Element = "stahl"
    quantity: int = 1
    # legendary items: free text effect from the world file, shown and narrated
    special: str | None = None
    # talismans: element whose affinity they raise
    affinity_element: Element | None = None


class Grave(BaseModel):
    location: str
    gold: int
    items: list[Item]
    turn: int


class Equipment(BaseModel):
    waffe: Item | None = None
    schild: Item | None = None
    ruestung: Item | None = None
    talisman: Item | None = None


class Character(BaseModel):
    id: str
    name: str
    class_id: str
    class_label: str
    element: Element
    background: str = ""
    joined_turn: int = 0

    xp: int = 0
    level: int = 1
    hp: int
    attribute_increases: list[Attribute] = Field(default_factory=list)
    # named by the player in advance, used at the next attribute increase (§9)
    attribute_choice: Attribute | None = None
    affinity: dict[Element, int] = Field(default_factory=dict)

    abilities: list[str] = Field(default_factory=list)
    cooldowns: dict[str, int] = Field(default_factory=dict)
    # second ability: chosen in advance, or offered at level 5 (§9)
    ability_choice: str | None = None
    ability_offer_turn: int | None = None

    equipment: Equipment = Field(default_factory=Equipment)
    bag: list[Item] = Field(default_factory=list)
    gold: int = 0

    location: str = ""
    previous_location: str = ""
    last_rest_point: str = ""
    shrines_used: list[str] = Field(default_factory=list)
    status: Literal["active", "camp", "left"] = "active"
    down: bool = False
    idle_streak: int = 0
    grave: Grave | None = None
