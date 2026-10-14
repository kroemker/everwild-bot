"""Plays many fights with simple tactics to tune the combat numbers (design §7).

Usage:
    python sim/combat_sim.py                 # default table
    python sim/combat_sim.py --fights 5000   # more fights per cell

Each cell is a random party of the given size and level against an encounter
of the same region level. A fight may last several turns (cooldowns tick
between turns, no healing in between), like it would in the game.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from everwild.catalog import Catalog, default_catalog  # noqa: E402
from everwild.models import Character  # noqa: E402
from everwild.rules import character as ch  # noqa: E402
from everwild.rules.combat import Tactic, resolve_fight  # noqa: E402
from everwild.rules.enemies import EnemySpec, build_enemies  # noqa: E402
from everwild.rules.items import find_consumable  # noqa: E402

CLASSES = ["krieger", "waldlaeufer", "magier", "kleriker", "schurke", "barde"]
ELEMENTS = ["feuer", "wasser", "erde", "luft", "licht", "schatten", "stahl"]
# second ability each class picks in the simulation
SECOND = {
    "krieger": "schlachtruf", "waldlaeufer": "pfeilhagel", "magier": "elementarbarriere",
    "kleriker": "gruppenheilung", "schurke": "hinterhalt", "barde": "heldenlied",
}

ENCOUNTERS: dict[str, list[EnemySpec]] = {
    "leicht": [EnemySpec("Goblin", "schwach", (), 2)],
    "standard": [EnemySpec("Wolf", "normal", (), 1), EnemySpec("Ratte", "schwach", (), 1)],
    "hart": [EnemySpec("Oger", "stark", (), 1), EnemySpec("Wolf", "normal", (), 1)],
    "elite": [EnemySpec("Hauptmann", "elite", (), 1), EnemySpec("Wache", "normal", (), 1)],
    "boss": [EnemySpec("Sumpfkönig", "boss", ("wasser",), 1)],
}
MAX_TURNS = {"leicht": 3, "standard": 3, "hart": 4, "elite": 4, "boss": 5}


def make_party(catalog: Catalog, rng: random.Random, size: int, level: int, length: str) -> list[Character]:
    party = []
    for n in range(size):
        cls = CLASSES[n % len(CLASSES)] if size >= len(CLASSES) else rng.choice(CLASSES)
        player = ch.create_character(catalog, rng, id=f"p{n}", name=f"{cls}{n}", class_id=cls,
                                     element=rng.choice(ELEMENTS))
        player.ability_choice = SECOND[cls]
        ch.set_xp(catalog, player, ch.level_start_xp(catalog, level, length), length)
        player.hp = ch.max_hp(catalog, player)
        if level >= 4:
            for slot in ("waffe", "ruestung"):
                item = getattr(player.equipment, slot)
                if item is not None:
                    item.rarity = "selten"
        party.append(player)
    return party


def choose_tactic(catalog: Catalog, player: Character, party: list[Character], enemies) -> Tactic:
    alive = [e for e in enemies if e.alive]
    hurt = [p for p in party if p.down or p.hp < ch.max_hp(catalog, p) * 0.4]

    if player.class_id == "kleriker" and hurt:
        for ability in ("gruppenheilung", "heilung"):
            if ch.ability_ready(player, ability) and (ability == "heilung" or len(hurt) > 1):
                return Tactic("faehigkeit", ability=ability, target=min(hurt, key=lambda p: p.hp).id)
    if player.hp < ch.max_hp(catalog, player) * 0.3:
        potion = find_consumable(catalog, player, "heiltrank")
        if potion is not None:
            return Tactic("gegenstand", item_id=potion.id)

    for ability in player.abilities:
        if not ch.ability_ready(player, ability) or not catalog.abilities[ability].combat:
            continue
        if ability in ("heilung", "gruppenheilung", "rauchbombe", "schutzsegen"):
            continue
        if ability in ("feuerball", "wirbelwind", "pfeilhagel") and len(alive) < 2:
            continue
        return Tactic("faehigkeit", ability=ability)
    return Tactic("angriff")


@dataclass
class Stats:
    fights: int = 0
    won: int = 0
    wiped: int = 0
    unfinished: int = 0
    turns: int = 0
    someone_down: int = 0
    deaths: int = 0
    hp_left: float = 0.0


def run_fight(catalog: Catalog, rng: random.Random, size: int, level: int, kind: str, length: str, stats: Stats) -> None:
    party = make_party(catalog, rng, size, level, length)
    enemies = build_enemies(catalog, ENCOUNTERS[kind], level, size)
    went_down = False
    stats.fights += 1
    for turn in range(1, MAX_TURNS[kind] + 1):
        if turn > 1:
            for p in party:
                ch.tick_cooldowns(p)
        fighters = [p for p in party if p.hp > 0 or p.down]
        tactics = {p.id: choose_tactic(catalog, p, fighters, enemies) for p in fighters}
        result = resolve_fight(catalog, rng, fighters, tactics, enemies)
        went_down |= any(e.kind == "kampfunfaehig" for e in result.events)
        if result.outcome == "offen":
            continue
        stats.turns += turn
        if result.outcome == "gewonnen":
            stats.won += 1
            stats.hp_left += sum(p.hp / ch.max_hp(catalog, p) for p in party) / len(party)
        else:
            stats.wiped += 1
            stats.deaths += len(result.died)
        stats.someone_down += went_down
        return
    stats.unfinished += 1
    stats.turns += MAX_TURNS[kind]
    stats.someone_down += went_down


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fights", type=int, default=1000)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1, 2, 4, 6])
    parser.add_argument("--levels", type=int, nargs="+", default=[1, 3, 5, 8])
    parser.add_argument("--encounters", nargs="+", default=list(ENCOUNTERS))
    parser.add_argument("--length", default="mittel")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    catalog = default_catalog()
    rng = random.Random(args.seed)
    print(f"{'Kampf':<9}{'Gruppe':>7}{'Stufe':>6}{'Sieg':>7}{'Tod':>6}{'offen':>7}{'Runden':>8}{'jemand k.o.':>13}{'LP übrig':>10}")
    for kind in args.encounters:
        for size in args.sizes:
            for level in args.levels:
                stats = Stats()
                for _ in range(args.fights):
                    run_fight(catalog, rng, size, level, kind, args.length, stats)
                n = stats.fights
                print(f"{kind:<9}{size:>7}{level:>6}"
                      f"{stats.won / n:>7.0%}{stats.wiped / n:>6.0%}{stats.unfinished / n:>7.0%}"
                      f"{stats.turns / n:>8.1f}{stats.someone_down / n:>13.0%}"
                      f"{(stats.hp_left / stats.won if stats.won else 0):>10.0%}")
        print()


if __name__ == "__main__":
    main()
