"""Enemy stats from tiers, scaled by region level and group size (design §7)."""

from __future__ import annotations

from dataclasses import dataclass

from ..catalog import Catalog
from ..models import Element, Tier


@dataclass(frozen=True)
class EnemySpec:
    """One kind of creature in an encounter, as stored in the world file.

    ``count`` is the number for a single player; it grows with the group.
    """

    name: str
    tier: Tier
    elements: tuple[Element, ...] = ()
    count: int = 1


@dataclass
class Enemy:
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

    @property
    def alive(self) -> bool:
        return self.hp > 0 and not self.fled

    @property
    def attack_element(self) -> Element:
        return next((e for e in self.elements if e != "stahl"), "stahl")


def scaled_count(catalog: Catalog, spec: EnemySpec, players: int) -> int:
    tier = catalog.enemies.tiers[spec.tier]
    if tier.hp_per_player:
        return spec.count
    extra = catalog.enemies.group_scaling.extra_per_player
    return max(1, int(spec.count * (1 + extra * (players - 1)) + 0.5))


def build_enemies(catalog: Catalog, specs: list[EnemySpec], region_level: int, players: int) -> list[Enemy]:
    scaling = catalog.enemies.region_scaling
    steps = region_level - 1
    enemies: list[Enemy] = []
    for spec in specs:
        tier = catalog.enemies.tiers[spec.tier]
        per_level = scaling.hp_per_level if tier.hp_per_level is None else tier.hp_per_level
        hp = tier.hp * (1 + per_level * steps)
        if tier.hp_per_player:
            hp *= max(1, players)
        hp = max(1, int(hp + 0.5))
        count = scaled_count(catalog, spec, players)
        for n in range(count):
            label = spec.name if count == 1 else f"{spec.name} {n + 1}"
            enemies.append(Enemy(
                id=f"{spec.name.lower().replace(' ', '-')}-{n + 1}",
                name=label,
                tier=spec.tier,
                elements=list(spec.elements),
                hp=hp,
                max_hp=hp,
                defense=tier.defense + steps // scaling.defense_every_levels,
                attack=tier.attack + steps // scaling.attack_every_levels,
                damage=tier.damage,
                damage_bonus=steps // scaling.damage_every_levels,
                attacks=1 + int(tier.extra_attacks_per_player * (players - 1) + 0.5),
            ))
    return enemies


def encounter_xp(catalog: Catalog, specs: list[EnemySpec]) -> int:
    """XP of a fair fight for one player: the unscaled enemy counts (§9)."""
    return sum(catalog.rules.xp.enemy[spec.tier] * spec.count for spec in specs)


def health_words(enemy: Enemy) -> str:
    """Enemy health in words for the narrator (§7)."""
    if enemy.fled:
        return "geflohen"
    if enemy.hp <= 0:
        return "besiegt"
    ratio = enemy.hp / enemy.max_hp
    if ratio >= 1:
        return "unverletzt"
    if ratio > 0.66:
        return "leicht verwundet"
    if ratio > 0.33:
        return "verwundet"
    return "schwer verwundet"
