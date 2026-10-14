"""The daily turn and starting a game in Discord (design §3, §15, §16).

Order of a turn, so that a crashed run can simply be repeated:
1. Post a chapter that was committed but not posted yet (and stop).
2. Read new messages, run the turn, narrate.
3. Save state and chapter, **commit and push**.
4. Post the chapter, update the 📖 Weltbuch thread and the channel topic.
5. Mark the turn as posted, commit again.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

from .catalog import Catalog
from .discord_api import CHECK, Discord
from .discord_render import (
    finale_messages, howto_text, prologue_messages, quest_log_embed, sheet_embed, topic_text, turn_messages,
)
from .engine import TurnEngine
from .interpret import Interpreter
from .narrate import epilogue, narrate_group, update_summary
from .render import chapter_text
from .rules.dice import seeded_rng
from .state import GameState, load_game, save_chapter, save_game
from .worldgen import generate_world

logger = logging.getLogger("everwild.bot")
Commit = Callable[[list[Path], str], object]
OOC_PREFIX = "//"


def no_commit(paths: list[Path], message: str) -> None:
    logger.info("(ohne Commit) %s", message)


def step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def collect_texts(discord: Discord, channel_id: str, state: GameState) -> tuple[dict[str, str], dict[str, str], list[str], str | None]:
    """New player messages since the last turn: texts and names per author,
    ids to confirm with ✅, and the newest message id.
    """
    bot_id = discord.me()["id"]
    messages = discord.messages_after(channel_id, state.last_message_id)
    texts: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    counted: list[str] = []
    for message in messages:
        author = message["author"]
        content = (message.get("content") or "").strip()
        if author["id"] == bot_id or author.get("bot") or not content or content.startswith(OOC_PREFIX):
            continue
        texts.setdefault(author["id"], []).append(content)
        names[author["id"]] = author.get("global_name") or author.get("username") or author["id"]
        counted.append(message["id"])
    newest = messages[-1]["id"] if messages else state.last_message_id
    return {k: "\n".join(v) for k, v in texts.items()}, names, counted, newest


def _chapter_payload_path(directory: Path, turn: int) -> Path:
    return directory / "chronik" / f"tag-{turn:03d}.json"


def _post(discord: Discord, channel_id: str, messages: list[dict]) -> None:
    for message in messages:
        discord.send(channel_id, message["content"], message["embeds"], mentions=message["mentions"])


def update_weltbuch(catalog: Catalog, state: GameState, discord: Discord) -> None:
    ids = state.discord
    if ids.thread is None:
        return
    discord.modify_channel(ids.thread, archived=False)  # threads archive themselves after a week
    if ids.quest_log:
        discord.edit(ids.thread, ids.quest_log, embeds=[quest_log_embed(catalog, state)])
    for player in state.players.values():
        embed = sheet_embed(catalog, state, player)
        if player.id in ids.sheets:
            discord.edit(ids.thread, ids.sheets[player.id], embeds=[embed])
        else:
            ids.sheets[player.id] = discord.send(ids.thread, "", [embed])["id"]


def _publish(catalog: Catalog, state: GameState, discord: Discord, channel_id: str, directory: Path, commit: Commit) -> None:
    payload = json.loads(_chapter_payload_path(directory, state.turn).read_text(encoding="utf-8"))
    _post(discord, channel_id, payload["messages"])
    update_weltbuch(catalog, state, discord)
    discord.modify_channel(channel_id, topic=topic_text(state))
    state.posted_turn = state.turn
    save_game(state, directory)
    commit([directory], f"Everwild: Tag {state.turn} gepostet")


def run_daily_turn(catalog: Catalog, directory: Path, discord: Discord, channel_id: str, llm=None,
                   commit: Commit = no_commit, dry_run: bool = False) -> str:
    """One scheduled run. Returns what happened, for the log."""
    state = load_game(directory)
    if state.posted_turn < state.turn:
        if dry_run:
            return f"Tag {state.turn} ist gespeichert, aber noch nicht gepostet (Probelauf: nichts gepostet)."
        _publish(catalog, state, discord, channel_id, directory, commit)
        return f"Tag {state.turn} nachträglich gepostet."
    if state.finished:
        return "Das Abenteuer ist vorbei."
    if state.paused:
        return "Pausiert."

    texts, names, counted, newest = collect_texts(discord, channel_id, state)
    rng = seeded_rng(state.game_id, state.turn + 1)
    report = TurnEngine(catalog, state, rng, Interpreter(llm=llm)).run_turn(texts, names)
    for group in report.groups:
        narrate_group(catalog, state, group, llm)
    update_summary(state, report, llm)
    messages = turn_messages(catalog, state, report)
    if report.finished:
        messages += finale_messages(state, epilogue(catalog, state, llm))
    text = chapter_text(catalog, state, report, mention=lambda p: f"@{p.name}")
    step_summary(f"## Tag {report.turn}\n\n**Eingaben**\n\n```\n{json.dumps(texts, ensure_ascii=False, indent=1)}\n```\n\n"
                 f"**Ereignisse**\n\n" + "\n".join(f"- {f}" for g in report.groups for f in g.facts) + f"\n\n**Kapitel**\n\n{text}")
    if dry_run:
        return text

    for message_id in counted:
        discord.react(channel_id, message_id, CHECK)
    state.last_message_id = newest
    save_game(state, directory)
    save_chapter(directory, report.turn, text)
    _chapter_payload_path(directory, report.turn).write_text(
        json.dumps({"messages": messages}, ensure_ascii=False, indent=1), encoding="utf-8")
    commit([directory], f"Everwild: Tag {report.turn}")
    _publish(catalog, state, discord, channel_id, directory, commit)
    return text


def start_game(catalog: Catalog, directory: Path, discord: Discord, channel_id: str, *, length: str, theme: str = "",
               archive: bool = False, llm=None, commit: Commit = no_commit, seed: str | None = None,
               archive_root: Path = Path("archive")) -> GameState:
    """The "Neues Spiel" workflow: world, prologue, how-to, Weltbuch thread (§15)."""
    moved: list[Path] = []
    if (directory / "state.json").exists():
        old = load_game(directory)
        if not old.finished and not archive:
            raise RuntimeError("Es läuft noch ein Spiel. Zum Ersetzen „Altes Spiel archivieren“ ankreuzen.")
        target = archive_root / f"{date.today().isoformat()}-{old.game_id}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(directory), str(target))
        moved = [target]

    game_id = seed or f"spiel-{date.today().isoformat()}"
    world = generate_world(catalog, length, seeded_rng(game_id, 0, "welt"), llm=llm, theme=theme)
    state = GameState(game_id=game_id, length=length, world=world)

    _post(discord, channel_id, prologue_messages(state))
    howto = discord.send(channel_id, howto_text(catalog))
    discord.pin(channel_id, howto["id"])
    thread = discord.start_thread(channel_id, howto["id"], "📖 Weltbuch")
    discord.modify_channel(thread["id"], locked=True)
    quest_log = discord.send(thread["id"], "", [quest_log_embed(catalog, state)])
    state.discord.howto, state.discord.thread, state.discord.quest_log = howto["id"], thread["id"], quest_log["id"]
    state.last_message_id = howto["id"]
    discord.modify_channel(channel_id, topic=topic_text(state))
    save_game(state, directory)
    commit([directory, *moved, archive_root] if moved else [directory], f"Everwild: neues Spiel ({world.name}, {length})")
    return state
