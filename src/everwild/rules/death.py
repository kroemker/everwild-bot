"""Death, resurrection and graves (design §10)."""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..catalog import Catalog
from ..models import Character, Grave, Item
from . import character as ch
from .items import has_room, is_quest_item


@dataclass
class DeathResult:
    grave: Grave
    lost_grave: Grave | None
    xp_lost: int


def die(catalog: Catalog, rng: random.Random, character: Character, *, turn: int, length: str) -> DeathResult:
    """Applies death: grave at the place of death, XP back to the level start,
    resurrection at the last rest point with full HP and no cooldowns.
    """
    gold_lost = -(-character.gold // 2)
    candidates = [item for item in character.bag if not is_quest_item(catalog, item)]
    count = -(-len(candidates) // 2)
    lost_items = rng.sample(candidates, count) if count else []
    for item in lost_items:
        character.bag.remove(item)
    character.gold -= gold_lost

    lost_grave = character.grave
    grave = Grave(location=character.location, gold=gold_lost, items=lost_items, turn=turn)
    character.grave = grave

    start = ch.level_start_xp(catalog, character.level, length)
    xp_lost = character.xp - start
    character.xp = start

    character.down = False
    character.hp = ch.max_hp(catalog, character)
    character.cooldowns = {}
    character.location = character.last_rest_point
    return DeathResult(grave=grave, lost_grave=lost_grave, xp_lost=xp_lost)


def recover_grave(catalog: Catalog, character: Character) -> tuple[int, list[Item]]:
    """Owner only, at the grave's location. Items that don't fit stay in the grave."""
    grave = character.grave
    if grave is None or grave.location != character.location:
        return 0, []
    character.gold += grave.gold
    recovered: list[Item] = []
    remaining: list[Item] = []
    for item in grave.items:
        if has_room(catalog, character, item):
            character.bag.append(item)
            recovered.append(item)
        else:
            remaining.append(item)
    gold = grave.gold
    if remaining:
        character.grave = grave.model_copy(update={"gold": 0, "items": remaining})
    else:
        character.grave = None
    return gold, recovered
