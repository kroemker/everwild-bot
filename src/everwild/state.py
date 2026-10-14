"""The whole game state and how it is stored on disk (design §17).

Layout of a game directory::

    world.json                 the world, including what changed during play
    state.json                 turn counter, settings, chronicle summary
    players/<id>.json          one file per character
    chronik/tag-012.md         the chapter of each turn
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .models import Character
from .world import World


class DiscordIds(BaseModel):
    """Messages the bot edits in place (design §16)."""

    howto: str | None = None
    thread: str | None = None
    quest_log: str | None = None
    sheets: dict[str, str] = Field(default_factory=dict)


class GameState(BaseModel):
    game_id: str
    length: str = "mittel"
    turn: int = 0
    paused: bool = False
    finished: bool = False
    summary: str = ""
    last_message_id: str | None = None
    posted_turn: int = 0  # the chapter of this turn has been posted (safe re-runs, §3)
    discord: DiscordIds = Field(default_factory=DiscordIds)
    world: World
    players: dict[str, Character] = Field(default_factory=dict)

    def active_players(self) -> list[Character]:
        return [p for p in self.players.values() if p.status == "active"]

    def average_level(self) -> float | None:
        active = self.active_players()
        if not active:
            return None
        return sum(p.level for p in active) / len(active)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_game(state: GameState, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _write_json(directory / "world.json", state.world.model_dump(mode="json"))
    meta = state.model_dump(mode="json", exclude={"world", "players"})
    _write_json(directory / "state.json", meta)
    players_dir = directory / "players"
    players_dir.mkdir(exist_ok=True)
    for old in players_dir.glob("*.json"):
        if old.stem not in state.players:
            old.unlink()
    for player in state.players.values():
        _write_json(players_dir / f"{player.id}.json", player.model_dump(mode="json"))


def load_game(directory: Path) -> GameState:
    meta = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    world = World.model_validate_json((directory / "world.json").read_text(encoding="utf-8"))
    players = {}
    for path in sorted((directory / "players").glob("*.json")):
        player = Character.model_validate_json(path.read_text(encoding="utf-8"))
        players[player.id] = player
    return GameState(world=world, players=players, **meta)


def save_chapter(directory: Path, turn: int, text: str) -> Path:
    path = directory / "chronik" / f"tag-{turn:03d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
