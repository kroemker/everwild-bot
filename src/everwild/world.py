"""The generated world: regions, locations, NPCs (design §11, §12).

Generated once at game start (step 3) and stored in ``world.json``. During
play only a few fields change: discovered flags, found features and paths,
defeated encounters, items lying around, state notes, NPC attitude and memory.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import Attribute, Element, Item, Rarity, Tier

LocationType = Literal["siedlung", "schrein", "wildnis", "dungeon", "hort"]
ATTITUDES = ["feindlich", "misstrauisch", "neutral", "freundlich", "verbündet"]


class ItemSpec(BaseModel):
    """An item to be created when found (hidden in a feature, carried by a boss)."""

    base: str
    name: str | None = None
    rarity: Rarity = "gewoehnlich"
    element: Element = "stahl"
    special: str | None = None
    quantity: int = 1


class Feature(BaseModel):
    """A permanent, concrete thing at a location (*Merkmal*, §11)."""

    id: str
    name: str
    description: str = ""
    hidden_item: ItemSpec | None = None
    hidden_path: str | None = None  # location id of a hidden connection
    search_difficulty: str = "mittel"
    searched: bool = False


class Requirement(BaseModel):
    """What a locked path needs (§11). ``text`` explains it in German."""

    kind: Literal["item", "affinity", "class", "check", "defeated"]
    text: str
    item_base: str | None = None
    item_name: str | None = None
    element: Element | None = None
    level: int = 1
    class_id: str | None = None
    attribute: Attribute | None = None
    difficulty: str | None = None
    location: str | None = None  # "defeated": the encounter at this location


class Connection(BaseModel):
    to: str
    requirement: Requirement | None = None
    hidden: bool = False
    found: bool = False
    opened: bool = False  # a "check" requirement stays open once passed


class EnemyEntry(BaseModel):
    name: str
    tier: Tier
    elements: list[Element] = Field(default_factory=list)
    count: int = 1


class LiveEnemy(BaseModel):
    """An enemy in a fight that continues over several turns."""

    id: str
    name: str
    tier: Tier
    elements: list[Element]
    hp: int
    max_hp: int
    defense: int
    attack: int
    damage: str
    damage_bonus: int
    attacks: int = 1
    fled: bool = False


class Encounter(BaseModel):
    enemies: list[EnemyEntry]
    description: str = ""
    ambush: bool = False
    state: Literal["feindlich", "besiegt", "friedlich"] = "feindlich"
    seen_turn: int | None = None  # when players first saw the threat
    live: list[LiveEnemy] = Field(default_factory=list)  # running fight
    loot: ItemSpec | None = None  # a guaranteed drop (bosses)


class Location(BaseModel):
    id: str
    name: str
    region: str
    type: LocationType
    description: str
    features: list[Feature] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    encounter: Encounter | None = None
    npcs: list[str] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    rest_point: bool = False
    inn: bool = False
    shrine_element: Element | None = None
    state_notes: list[str] = Field(default_factory=list)
    discovered: bool = False


class Region(BaseModel):
    id: str
    name: str
    elements: list[Element]
    level: int = 1
    mood: str


class People(BaseModel):
    id: str
    name: str
    elements: list[Element]
    description: str
    attitude: int = 0  # -2 feindlich … +2 verbündet


class NPC(BaseModel):
    id: str
    name: str
    people: str | None = None
    location: str
    role: str
    appearance: str
    personality: str
    speech: str
    knowledge: list[str] = Field(default_factory=list)
    wants: str = ""
    attitude: int = 0  # -2 feindlich … +2 verbündet
    memory: list[str] = Field(default_factory=list)
    indispensable: bool = False
    shop: list[str] = Field(default_factory=list)  # item bases for sale
    alive: bool = True


class World(BaseModel):
    name: str
    premise: str
    start_location: str
    regions: dict[str, Region]
    locations: dict[str, Location]
    npcs: dict[str, NPC] = Field(default_factory=dict)
    peoples: dict[str, People] = Field(default_factory=dict)

    def location(self, location_id: str) -> Location:
        return self.locations[location_id]

    def region_of(self, location_id: str) -> Region:
        return self.regions[self.locations[location_id].region]

    def npcs_at(self, location_id: str) -> list[NPC]:
        return [self.npcs[n] for n in self.locations[location_id].npcs if n in self.npcs and self.npcs[n].alive]

    def visible_connections(self, location_id: str) -> list[Connection]:
        return [c for c in self.locations[location_id].connections if not c.hidden or c.found]

    def validate_references(self) -> None:
        if self.start_location not in self.locations:
            raise ValueError(f"Unbekannter Startort: {self.start_location}")
        for loc in self.locations.values():
            if loc.region not in self.regions:
                raise ValueError(f"{loc.id}: unbekannte Region {loc.region}")
            for con in loc.connections:
                if con.to not in self.locations:
                    raise ValueError(f"{loc.id}: Weg zu unbekanntem Ort {con.to}")
            for npc in loc.npcs:
                if npc not in self.npcs:
                    raise ValueError(f"{loc.id}: unbekannter NSC {npc}")
            for feature in loc.features:
                if feature.hidden_path and not any(c.to == feature.hidden_path and c.hidden for c in loc.connections):
                    raise ValueError(f"{loc.id}/{feature.id}: kein versteckter Weg nach {feature.hidden_path}")


def attitude_label(value: int) -> str:
    return ATTITUDES[max(-2, min(2, value)) + 2]
