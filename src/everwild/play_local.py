"""Local play mode: the whole game in the terminal (design §17).

    python -m everwild play                      # interactive
    python -m everwild play --script runde.txt   # scripted, e.g. for tests

Without a world file, ``--generieren`` creates a new world (with the LLM if
configured, else from word lists); ``--thema`` gives the generator a hint.

Type ``name: what the character does``. The name before the colon is the
player; a new name joins the game. An empty line (or ``:runde``) ends the
day. Commands: ``:bogen NAME``, ``:karte``, ``:quests``, ``:spieler``, ``:hilfe``, ``:ende``.

Without OPENAI_API_KEY (or with ``--offline``) the offline interpreter and
narrator are used.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .catalog import default_catalog
from .engine import TurnEngine
from .interpret import Interpreter
from .llm import get_llm
from .narrate import epilogue, narrate_group, update_summary
from .render import chapter_text, map_text, quest_log_text, sheet_text, stats_text
from .rules.dice import seeded_rng
from .state import GameState, load_game, save_chapter, save_game
from .world import Location, Region, World
from .worldgen import generate_world

DEFAULT_WORLD = Path(__file__).resolve().parents[2] / "examples" / "testwelt.json"
HELP = __doc__.split("\n\n", 2)[2]


def new_game(world_path: Path, length: str, game_id: str) -> GameState:
    world = World.model_validate_json(world_path.read_text(encoding="utf-8"))
    world.validate_references()
    return GameState(game_id=game_id, length=length, world=world)


def placeholder_world() -> World:
    """An empty world until the real one is generated."""
    return World(name="", premise="", start_location="x", regions={"x": Region(id="x", name="", elements=[], mood="")},
                 locations={"x": Location(id="x", name="", region="x", type="wildnis", description="")})


def player_key(name: str) -> str:
    return re.sub(r"\W+", "-", name.strip().lower()).strip("-") or "spieler"


class LocalGame:
    def __init__(self, state: GameState, directory: Path | None, offline: bool, out=print):
        self.catalog = default_catalog()
        self.state = state
        self.directory = directory
        self.llm = None if offline else get_llm()
        self.out = out
        self.pending: dict[str, list[str]] = {}
        self.names: dict[str, str] = {}

    def find(self, name: str):
        key = player_key(name)
        if key in self.state.players:
            return self.state.players[key]
        return next((p for p in self.state.players.values() if p.name.lower() == name.strip().lower()), None)

    def handle(self, line: str) -> bool:
        """Processes one input line. Returns False to quit."""
        line = line.strip()
        if not line or line == ":runde":
            self.run_turn()
            return True
        if line.startswith(":"):
            command, _, arg = line[1:].partition(" ")
            if command == "ende":
                return False
            if command == "karte":
                self.out(map_text(self.state))
            elif command == "quests":
                self.out(quest_log_text(self.catalog, self.state))
            elif command == "spieler":
                for p in self.state.players.values():
                    self.out(f"- {p.name} ({p.id}): {p.class_label}, Stufe {p.level}, {p.status}")
            elif command == "bogen":
                player = self.find(arg)
                self.out(sheet_text(self.catalog, self.state, player) if player else f"Unbekannt: {arg}")
            else:
                self.out(HELP)
            return True
        if ":" not in line:
            self.out("Format: NAME: was die Figur tut")
            return True
        name, _, text = line.partition(":")
        existing = self.find(name)
        key = existing.id if existing else player_key(name)
        self.names.setdefault(key, name.strip())
        self.pending.setdefault(key, []).append(text.strip())
        return True

    def run_turn(self) -> None:
        if self.state.finished:
            self.out("Das Abenteuer ist vorbei.")
            return
        texts = {pid: "\n".join(lines) for pid, lines in self.pending.items()}
        self.pending.clear()
        state = self.state
        rng = seeded_rng(state.game_id, state.turn + 1)
        engine = TurnEngine(self.catalog, state, rng, Interpreter(llm=self.llm))
        report = engine.run_turn(texts, self.names)
        for group in report.groups:
            narrate_group(self.catalog, state, group, self.llm)
        update_summary(state, report, self.llm)
        text = chapter_text(self.catalog, state, report)
        if report.finished:
            text += "\n" + epilogue(self.catalog, state, self.llm) + "\n\n" + stats_text(state) + "\n"
        self.out(text)
        if self.directory is not None:
            save_game(state, self.directory)
            save_chapter(self.directory, report.turn, text)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="everwild play", description="Everwild lokal im Terminal spielen.")
    parser.add_argument("--world", type=Path, default=DEFAULT_WORLD, help="Welt-Datei für ein neues Spiel")
    parser.add_argument("--dir", type=Path, default=Path("lokales-spiel"), help="Spielstand-Ordner")
    parser.add_argument("--length", choices=["kurz", "mittel", "lang"], default="mittel")
    parser.add_argument("--neu", action="store_true", help="neues Spiel, auch wenn es einen Spielstand gibt")
    parser.add_argument("--offline", action="store_true", help="ohne LLM spielen")
    parser.add_argument("--script", type=Path, help="Datei mit Eingabezeilen statt Tastatur")
    parser.add_argument("--generieren", action="store_true", help="eine neue Welt erzeugen statt --world")
    parser.add_argument("--thema", default="", help="Hinweis für die Weltgenerierung")
    parser.add_argument("--seed", default=None, help="Zufallssaat der Weltgenerierung")
    args = parser.parse_args(argv)

    if (args.dir / "state.json").exists() and not args.neu:
        state = load_game(args.dir)
        game = LocalGame(state, args.dir, args.offline)
    elif args.generieren:
        game = LocalGame(GameState(game_id=args.dir.name, length=args.length, world=placeholder_world()), args.dir, args.offline)
        rng = seeded_rng(args.seed or args.dir.name, 0, "welt")
        print("Erzeuge die Welt …")
        world = generate_world(game.catalog, args.length, rng, llm=game.llm, theme=args.thema)
        game.state = GameState(game_id=args.dir.name, length=args.length, world=world)
        save_game(game.state, args.dir)
    else:
        state = new_game(args.world, args.length, game_id=args.dir.name)
        game = LocalGame(state, args.dir, args.offline)
    state = game.state
    mode = game.llm.name if game.llm else "offline"
    print(f"Everwild – {state.world.name} ({mode}). Tag {state.turn}. ':hilfe' für Hilfe.\n")
    if state.turn == 0:
        print(state.world.premise + "\n")

    lines = args.script.read_text(encoding="utf-8").splitlines() if args.script else None
    while True:
        if lines is not None:
            if not lines:
                if game.pending:
                    game.run_turn()
                break
            line = lines.pop(0)
            if line.startswith("#"):
                continue
            print(f"> {line}")
        else:
            try:
                line = input("> ")
            except EOFError:
                break
        if not game.handle(line):
            break


if __name__ == "__main__":
    main(sys.argv[1:])
