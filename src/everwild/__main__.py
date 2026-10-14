"""Entry point: ``python -m everwild <command>``.

Commands:
  play       play locally in the terminal (see ``python -m everwild play --help``)
  turn       the daily turn in Discord (GitHub workflow)
  new-game   start a new game in Discord (GitHub workflow)

Discord settings come from the environment: DISCORD_BOT_TOKEN, ADVENTURE_CHANNEL_ID.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


def _discord_and_channel():
    from .discord_api import DiscordREST

    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    channel = os.environ.get("ADVENTURE_CHANNEL_ID", "")
    if not token or not channel:
        raise SystemExit("DISCORD_BOT_TOKEN und ADVENTURE_CHANNEL_ID müssen gesetzt sein.")
    return DiscordREST(token), channel


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not argv or argv[0] not in ("play", "turn", "new-game"):
        print(__doc__)
        return
    command, rest = argv[0], argv[1:]
    if command == "play":
        from .play_local import main as play

        play(rest)
        return

    from .catalog import default_catalog
    from .gitops import commit_and_push
    from .llm import get_llm

    parser = argparse.ArgumentParser(prog=f"everwild {command}")
    parser.add_argument("--dir", type=Path, default=Path("game"))
    parser.add_argument("--no-git", action="store_true", help="nichts committen")
    if command == "turn":
        parser.add_argument("--dry-run", action="store_true", help="nichts posten, nichts speichern")
    else:
        parser.add_argument("--length", choices=["kurz", "mittel", "lang"], default="mittel")
        parser.add_argument("--theme", default="")
        parser.add_argument("--archive", action="store_true", help="laufendes Spiel archivieren und ersetzen")
    args = parser.parse_args(rest)

    from .bot import no_commit, run_daily_turn, start_game

    catalog = default_catalog()
    discord, channel = _discord_and_channel()
    commit = no_commit if args.no_git else commit_and_push
    llm = get_llm()
    if llm is None:
        logging.warning("Kein LLM konfiguriert – Offline-Interpretation und -Erzählung.")
    if command == "turn":
        print(run_daily_turn(catalog, args.dir, discord, channel, llm=llm, commit=commit, dry_run=args.dry_run))
    else:
        state = start_game(catalog, args.dir, discord, channel, length=args.length, theme=args.theme,
                           archive=args.archive, llm=llm, commit=commit)
        print(f"Neues Spiel: {state.world.name} ({state.length})")


if __name__ == "__main__":
    main()
