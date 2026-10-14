"""Element matchups and affinity (design §6)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from ..catalog import Catalog
from ..models import Character, Element

Matchup = Literal["stark", "schwach", "neutral"]


def matchup(catalog: Catalog, attack: Element, targets: Iterable[Element]) -> Matchup:
    """How an attack element fares against a target with 1–2 elements.

    Same element as the target: weak (half damage). Opposite element: strong
    (advantage, +50 % damage). A target with both the attack element and its
    opposite cancels out to neutral. Stahl is always neutral.
    """
    targets = set(targets) - {"stahl"}
    if attack == "stahl" or not targets:
        return "neutral"
    opposite = catalog.rules.elements[attack].opposite
    weak = attack in targets
    strong = opposite in targets
    if weak and strong:
        return "neutral"
    if strong:
        return "stark"
    if weak:
        return "schwach"
    return "neutral"


def damage_multiplier(catalog: Catalog, result: Matchup) -> float:
    if result == "stark":
        return catalog.rules.element_strong_multiplier
    if result == "schwach":
        return catalog.rules.element_weak_multiplier
    return 1.0


def apply_multiplier(damage: int, multiplier: float) -> int:
    """Rounds half up and never goes below 1 for a hit."""
    if damage <= 0:
        return 0
    return max(1, int(damage * multiplier + 0.5))


def effective_affinity(catalog: Catalog, character: Character, element: Element) -> int:
    """Affinity including an equipped talisman, capped at the maximum.

    A talisman's +1 ignores the two-element limit: it is equipment, not
    something the character has learned.
    """
    if element == "stahl":
        return 0
    value = character.affinity.get(element, 0)
    talisman = character.equipment.talisman
    if talisman is not None and talisman.affinity_element == element:
        value += 1
    return min(value, catalog.rules.affinity_max)


def resists(catalog: Catalog, character: Character, element: Element) -> bool:
    return effective_affinity(catalog, character, element) >= catalog.rules.affinity_resist_from


def can_gain_affinity(catalog: Catalog, character: Character, element: Element) -> bool:
    """At most two learned elements, never two opposites, max level 3."""
    if element == "stahl":
        return False
    current = character.affinity.get(element, 0)
    if current >= catalog.rules.affinity_max:
        return False
    if current > 0:
        return True
    learned = [e for e, v in character.affinity.items() if v > 0]
    if len(learned) >= catalog.rules.max_affinity_elements:
        return False
    opposite = catalog.rules.elements[element].opposite
    return opposite not in learned


def gain_affinity(catalog: Catalog, character: Character, element: Element) -> bool:
    if not can_gain_affinity(catalog, character, element):
        return False
    character.affinity[element] = character.affinity.get(element, 0) + 1
    return True
