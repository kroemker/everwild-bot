"""Items: creation, German names, bag, equipment, giving, prices (design §8)."""

from __future__ import annotations

import random

from ..catalog import Catalog
from ..models import Character, Element, Item, ItemBase, Rarity, Slot

_ADJECTIVE_ENDINGS = {"m": "er", "f": "e", "n": "es", "pl": "e"}
STACKABLE = {"verbrauchsgut"}


class ItemError(Exception):
    """A rule forbids the item operation. The message is player-facing German."""


def new_item_id(rng: random.Random, base: str) -> str:
    return f"{base}-{rng.getrandbits(32):08x}"


def make_item(
    catalog: Catalog,
    rng: random.Random,
    base: str,
    *,
    rarity: Rarity = "gewoehnlich",
    element: Element = "stahl",
    name: str | None = None,
    quantity: int = 1,
    special: str | None = None,
    affinity_element: Element | None = None,
) -> Item:
    if base not in catalog.items:
        raise ItemError(f"Unbekannter Gegenstand: {base}")
    item_base = catalog.items[base]
    if rarity == "legendaer" and name is None:
        raise ItemError("Legendäre Gegenstände brauchen einen Namen aus der Welt.")
    if item_base.category == "talisman" and affinity_element is None and element != "stahl":
        affinity_element = element
    return Item(
        id=new_item_id(rng, base),
        base=base,
        name=name or generate_name(catalog, rng, base, rarity, element),
        rarity=rarity,
        element=element,
        quantity=quantity,
        special=special,
        affinity_element=affinity_element,
    )


# --- names -------------------------------------------------------------------


def _inflect(adjective_stem: str, gender: str) -> str:
    word = adjective_stem + _ADJECTIVE_ENDINGS[gender]
    return word[0].upper() + word[1:]


def _compound(prefix: str, head: str) -> str:
    return prefix + head.lower()


def generate_name(catalog: Catalog, rng: random.Random, base: str, rarity: Rarity, element: Element) -> str:
    """Builds a German item name from the word lists (design §8, item names).

    Adjectives are only combined with the base name, whose grammatical gender
    is known; variants and compounds are used as they are.
    """
    item_base = catalog.items[base]
    names = catalog.names
    if rarity == "legendaer":
        raise ItemError("Legendäre Namen kommen aus der Weltgenerierung.")

    if rarity == "gewoehnlich" and element == "stahl":
        options: list[str] = list(item_base.variants or [item_base.name])
        if item_base.category in ("waffe", "schild", "ruestung"):
            options += [f"{_inflect(adj, item_base.gender)} {item_base.name}" for adj in names.common_adjectives]
        return rng.choice(options)

    if element == "stahl":
        options = [_compound(p, h) for p in names.quality_prefixes for h in item_base.heads]
        options += [f"{item_base.name} {g}" for g in names.quality_genitives]
        return rng.choice(options)

    words = names.elements[element]
    options = [_compound(p, h) for p in words.prefixes for h in item_base.heads]
    options += [f"{_inflect(adj, item_base.gender)} {item_base.name}" for adj in words.adjectives]
    options += [f"{item_base.name} {g}" for g in words.genitives]
    if rarity == "gewoehnlich":
        # a common item with an element gets the plain element adjective only
        options = [f"{_inflect(adj, item_base.gender)} {item_base.name}" for adj in words.adjectives]
    return rng.choice(options)


def display_name(catalog: Catalog, item: Item) -> str:
    marker = catalog.rules.rarities[item.rarity].marker
    label = f"{marker} {item.name}" if marker else item.name
    if item.quantity > 1:
        label += f" ×{item.quantity}"
    return label


def describe(catalog: Catalog, item: Item) -> str:
    """Name with base type, rarity and element: "◆ Frostklinge (Schwert, selten, 💧)"."""
    base = catalog.items[item.base]
    parts = [base.name]
    if item.rarity != "gewoehnlich":
        parts.append(catalog.rules.rarities[item.rarity].label.lower())
    if item.element != "stahl":
        parts.append(catalog.rules.elements[item.element].emoji)
    if item.name == base.name and len(parts) == 1:
        return display_name(catalog, item)
    return f"{display_name(catalog, item)} ({', '.join(parts)})"


# --- prices ------------------------------------------------------------------


def price(catalog: Catalog, item: Item) -> int:
    base = catalog.items[item.base]
    return base.price * catalog.rules.rarities[item.rarity].price_multiplier


def sell_price(catalog: Catalog, item: Item) -> int:
    if catalog.items[item.base].category == "questgegenstand":
        return 0
    return int(price(catalog, item) * catalog.rules.sell_price_fraction)


# --- bag ---------------------------------------------------------------------


def is_quest_item(catalog: Catalog, item: Item) -> bool:
    return catalog.items[item.base].category == "questgegenstand"


def slots_used(catalog: Catalog, character: Character) -> int:
    """Equipped and quest items don't count toward the bag limit."""
    return sum(1 for item in character.bag if not is_quest_item(catalog, item))


def _stack_key(item: Item) -> tuple:
    return (item.base, item.name, item.rarity, item.element)


def _slots_needed(catalog: Catalog, character: Character, item: Item) -> int:
    if is_quest_item(catalog, item):
        return 0
    if catalog.items[item.base].category not in STACKABLE:
        return 1
    stack = catalog.rules.stack_size
    remaining = item.quantity
    for existing in character.bag:
        if _stack_key(existing) == _stack_key(item):
            remaining -= max(0, stack - existing.quantity)
    if remaining <= 0:
        return 0
    return -(-remaining // stack)


def has_room(catalog: Catalog, character: Character, item: Item) -> bool:
    free = catalog.rules.bag_slots - slots_used(catalog, character)
    return _slots_needed(catalog, character, item) <= free


def add_to_bag(catalog: Catalog, character: Character, item: Item) -> None:
    """Adds an item, filling existing stacks first. Raises if the bag is full."""
    if not has_room(catalog, character, item):
        raise ItemError(f"Der Rucksack von {character.name} ist voll.")
    if catalog.items[item.base].category not in STACKABLE:
        character.bag.append(item)
        return
    stack = catalog.rules.stack_size
    remaining = item.quantity
    for existing in character.bag:
        if remaining and _stack_key(existing) == _stack_key(item) and existing.quantity < stack:
            moved = min(stack - existing.quantity, remaining)
            existing.quantity += moved
            remaining -= moved
    first = True
    while remaining:
        amount = min(stack, remaining)
        part = item if first else item.model_copy(update={"id": f"{item.id}-{len(character.bag)}"})
        part.quantity = amount
        character.bag.append(part)
        remaining -= amount
        first = False


def find_in_bag(character: Character, item_id: str) -> Item:
    for item in character.bag:
        if item.id == item_id:
            return item
    raise ItemError(f"{character.name} hat diesen Gegenstand nicht im Rucksack.")


def remove_from_bag(character: Character, item_id: str, quantity: int = 1) -> Item:
    """Removes ``quantity`` of a stack (or the whole item) and returns the removed part."""
    item = find_in_bag(character, item_id)
    if quantity >= item.quantity:
        character.bag.remove(item)
        return item
    item.quantity -= quantity
    return item.model_copy(update={"quantity": quantity})


def find_consumable(catalog: Catalog, character: Character, base: str) -> Item | None:
    for item in character.bag:
        if item.base == base:
            return item
    return None


# --- equipment ---------------------------------------------------------------


def slot_for(catalog: Catalog, item: Item) -> Slot:
    category = catalog.items[item.base].category
    if category not in ("waffe", "schild", "ruestung", "talisman"):
        raise ItemError(f"{item.name} kann man nicht ausrüsten.")
    return category  # type: ignore[return-value]


def can_use(catalog: Catalog, character: Character, base: ItemBase) -> bool:
    return base.classes is None or character.class_id in base.classes


def equip(catalog: Catalog, character: Character, item_id: str) -> list[Item]:
    """Equips an item from the bag. Returns the items that went back into the bag.

    Equipping is free and doesn't use the action (design §8).
    """
    item = find_in_bag(character, item_id)
    slot = slot_for(catalog, item)
    base = catalog.items[item.base]
    if not can_use(catalog, character, base):
        raise ItemError(f"{character.class_label} können {base.name} nicht benutzen.")

    unequipped: list[Item] = []
    current = getattr(character.equipment, slot)
    if current is not None:
        unequipped.append(current)
    weapon = character.equipment.waffe
    if slot == "waffe" and base.two_handed and character.equipment.schild is not None:
        unequipped.append(character.equipment.schild)
    if slot == "schild" and weapon is not None and catalog.items[weapon.base].two_handed:
        unequipped.append(weapon)

    free_after = catalog.rules.bag_slots - slots_used(catalog, character) + 1
    if sum(1 for i in unequipped if not is_quest_item(catalog, i)) > free_after:
        raise ItemError(f"Im Rucksack von {character.name} ist kein Platz für die abgelegte Ausrüstung.")

    character.bag.remove(item)
    for old in unequipped:
        setattr(character.equipment, slot_for(catalog, old), None)
        character.bag.append(old)
    setattr(character.equipment, slot, item)
    return unequipped


def unequip(catalog: Catalog, character: Character, slot: Slot) -> Item:
    item = getattr(character.equipment, slot)
    if item is None:
        raise ItemError("Dort ist nichts ausgerüstet.")
    if not has_room(catalog, character, item):
        raise ItemError(f"Der Rucksack von {character.name} ist voll.")
    setattr(character.equipment, slot, None)
    character.bag.append(item)
    return item


# --- giving ------------------------------------------------------------------


def give(catalog: Catalog, giver: Character, receiver: Character, item_id: str, quantity: int = 1) -> Item:
    """Gives an item (from bag or equipment) to a player at the same location."""
    if giver.location != receiver.location:
        raise ItemError(f"{receiver.name} ist nicht am selben Ort.")
    for slot in ("waffe", "schild", "ruestung", "talisman"):
        equipped = getattr(giver.equipment, slot)
        if equipped is not None and equipped.id == item_id:
            if not has_room(catalog, receiver, equipped):
                raise ItemError(f"Der Rucksack von {receiver.name} ist voll.")
            setattr(giver.equipment, slot, None)
            add_to_bag(catalog, receiver, equipped)
            return equipped
    item = find_in_bag(giver, item_id)
    part = item.model_copy(update={"quantity": min(quantity, item.quantity)})
    if not has_room(catalog, receiver, part):
        raise ItemError(f"Der Rucksack von {receiver.name} ist voll.")
    removed = remove_from_bag(giver, item_id, quantity)
    add_to_bag(catalog, receiver, removed)
    return removed
