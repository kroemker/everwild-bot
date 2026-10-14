"""Dice, checks and the seeded random generator (design §5, §17)."""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from typing import Literal

Advantage = Literal["normal", "vorteil", "nachteil"]
Outcome = Literal["kritischer_erfolg", "erfolg", "erfolg_mit_haken", "fehlschlag", "kritischer_fehlschlag"]

_DICE = re.compile(r"^(\d+)d(\d+)$")


def seeded_rng(game_id: str, turn: int, salt: str = "") -> random.Random:
    """Same game, turn and salt always give the same dice."""
    digest = hashlib.sha256(f"{game_id}:{turn}:{salt}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def parse_dice(expr: str) -> tuple[int, int]:
    match = _DICE.match(expr.strip())
    if not match:
        raise ValueError(f"Ungültiger Würfelausdruck: {expr!r}")
    return int(match.group(1)), int(match.group(2))


def roll_dice(rng: random.Random, expr: str) -> list[int]:
    count, sides = parse_dice(expr)
    return [rng.randint(1, sides) for _ in range(count)]


def combine_advantage(*states: Advantage) -> Advantage:
    """Advantage and disadvantage cancel each other out and don't stack."""
    has_adv = "vorteil" in states
    has_dis = "nachteil" in states
    if has_adv and not has_dis:
        return "vorteil"
    if has_dis and not has_adv:
        return "nachteil"
    return "normal"


@dataclass(frozen=True)
class D20Roll:
    rolls: tuple[int, ...]
    kept: int
    advantage: Advantage

    @property
    def natural_20(self) -> bool:
        return self.kept == 20

    @property
    def natural_1(self) -> bool:
        return self.kept == 1


def roll_d20(rng: random.Random, advantage: Advantage = "normal") -> D20Roll:
    if advantage == "normal":
        value = rng.randint(1, 20)
        return D20Roll((value,), value, advantage)
    rolls = (rng.randint(1, 20), rng.randint(1, 20))
    kept = max(rolls) if advantage == "vorteil" else min(rolls)
    return D20Roll(rolls, kept, advantage)


@dataclass(frozen=True)
class CheckResult:
    roll: D20Roll
    modifier: int
    target: int
    outcome: Outcome

    @property
    def total(self) -> int:
        return self.roll.kept + self.modifier

    @property
    def succeeded(self) -> bool:
        return self.outcome in ("kritischer_erfolg", "erfolg", "erfolg_mit_haken")


def check(
    rng: random.Random,
    modifier: int,
    target: int,
    advantage: Advantage = "normal",
    complication_margin: int = 2,
) -> CheckResult:
    """d20 + modifier against a target number.

    A natural 20 always succeeds, a natural 1 always fails. Missing by
    ``complication_margin`` or less is a success with a complication.
    """
    roll = roll_d20(rng, advantage)
    total = roll.kept + modifier
    if roll.natural_20:
        outcome: Outcome = "kritischer_erfolg"
    elif roll.natural_1:
        outcome = "kritischer_fehlschlag"
    elif total >= target:
        outcome = "erfolg"
    elif target - total <= complication_margin:
        outcome = "erfolg_mit_haken"
    else:
        outcome = "fehlschlag"
    return CheckResult(roll, modifier, target, outcome)
