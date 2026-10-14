"""The Discord flow with an in-memory Discord, and the REST client with a mocked HTTP server."""

import json

import httpx
import pytest

from everwild.bot import collect_texts, run_daily_turn, start_game
from everwild.discord_api import DiscordREST, FakeDiscord
from everwild.discord_render import split_text
from everwild.state import load_game

CHANNEL = "100"


@pytest.fixture
def setup(catalog, tmp_path):
    discord = FakeDiscord()
    log: list[str] = []
    original_send = discord.send

    def send(*args, **kwargs):
        log.append("send")
        return original_send(*args, **kwargs)

    discord.send = send  # type: ignore[method-assign]

    def commit(paths, message):
        log.append(f"commit: {message}")

    game_dir = tmp_path / "game"
    start_game(catalog, game_dir, discord, CHANNEL, length="kurz", commit=commit, seed="test",
               archive_root=tmp_path / "archive")
    log.clear()
    return discord, game_dir, commit, log


def bot_messages(discord, channel=CHANNEL):
    return [m for m in discord.channels.get(channel, []) if m["author"].get("bot")]


def test_new_game_sets_up_the_channel(catalog, setup):
    discord, game_dir, _, _ = setup
    state = load_game(game_dir)
    ids = state.discord
    assert ids.howto in discord.pins
    assert discord.channel_info[ids.thread]["name"] == "📖 Weltbuch"
    assert discord.channel_info[ids.thread]["locked"] is True
    quest_log = discord.channels[ids.thread][0]
    assert quest_log["embeds"][0]["title"].startswith("📜 ")
    assert discord.channel_info[CHANNEL]["topic"].startswith("Tag 0")
    assert state.last_message_id == ids.howto
    assert state.world.name in bot_messages(discord)[0]["content"]


def test_a_daily_turn(catalog, setup):
    discord, game_dir, commit, log = setup
    joined = discord.user_message(CHANNEL, "11", "Lea", "Ich bin Brakka, eine Kriegerin des Feuers.")
    ooc = discord.user_message(CHANNEL, "12", "Tom", "// bin heute spät dran")
    later = discord.user_message(CHANNEL, "12", "Tom", "Ich heiße Mira, Klerikerin des Lichts.")
    text = run_daily_turn(catalog, game_dir, discord, CHANNEL, commit=commit)
    assert "Tag 1" in text

    state = load_game(game_dir)
    assert set(state.players) == {"11", "12"}
    assert state.posted_turn == state.turn == 1
    assert state.last_message_id == later["id"]
    confirmed = {message_id for _, message_id, _ in discord.reactions}
    assert confirmed == {joined["id"], later["id"]} and ooc["id"] not in confirmed

    # committed before anything was posted, then marked as posted
    assert log[0] == "commit: Everwild: Tag 1" and "send" in log[1:] and log[-1] == "commit: Everwild: Tag 1 gepostet"
    chapter = bot_messages(discord)
    assert any(m["content"].startswith("## ☀️ Tag 1") for m in chapter)
    group = next(m for m in chapter if m["content"].startswith("### 📍"))
    assert "<@11>" in group["content"] and "<@12>" in group["content"] and group["mentions"]
    assert group["embeds"][0]["title"] == "Ergebnis"
    sheets = [m for m in discord.channels[state.discord.thread] if m["embeds"] and "Stufe" in m["embeds"][0]["title"]]
    assert len(sheets) == 2 and set(state.discord.sheets) == {"11", "12"}
    assert discord.channel_info[CHANNEL]["topic"].startswith("Tag 1")
    assert (game_dir / "chronik" / "tag-001.md").exists()

    # the next day: sheets are edited, not posted again
    discord.user_message(CHANNEL, "11", "Lea", "Ich raste.")
    run_daily_turn(catalog, game_dir, discord, CHANNEL, commit=commit)
    state = load_game(game_dir)
    assert len([m for m in discord.channels[state.discord.thread] if m["embeds"]]) == 3  # quest log + 2 sheets
    assert any(c == f"edit {state.discord.thread}/{state.discord.sheets['11']}" for c in discord.calls)


def test_crash_after_commit_reposts_instead_of_replaying(catalog, setup):
    discord, game_dir, commit, _ = setup
    discord.user_message(CHANNEL, "11", "Lea", "Ich bin Brakka, eine Kriegerin des Feuers.")
    send = discord.send

    def broken_send(*args, **kwargs):
        raise RuntimeError("Discord ist weg")

    discord.send = broken_send  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        run_daily_turn(catalog, game_dir, discord, CHANNEL, commit=commit)
    state = load_game(game_dir)
    assert state.turn == 1 and state.posted_turn == 0

    discord.send = send  # type: ignore[method-assign]
    result = run_daily_turn(catalog, game_dir, discord, CHANNEL, commit=commit)
    assert "nachträglich" in result
    state = load_game(game_dir)
    assert state.turn == 1 and state.posted_turn == 1
    assert sum(m["content"].startswith("## ☀️ Tag 1") for m in bot_messages(discord)) == 1


def test_dry_run_changes_nothing(catalog, setup):
    discord, game_dir, commit, log = setup
    discord.user_message(CHANNEL, "11", "Lea", "Ich bin Brakka, eine Kriegerin des Feuers.")
    before = (game_dir / "state.json").read_text()
    text = run_daily_turn(catalog, game_dir, discord, CHANNEL, commit=commit, dry_run=True)
    assert "Tag 1" in text
    assert (game_dir / "state.json").read_text() == before
    assert log == [] and discord.reactions == []


def test_paused_and_finished_games_do_nothing(catalog, setup):
    discord, game_dir, commit, _ = setup
    state = load_game(game_dir)
    state.paused = True
    from everwild.state import save_game
    save_game(state, game_dir)
    assert run_daily_turn(catalog, game_dir, discord, CHANNEL, commit=commit) == "Pausiert."


def test_running_game_is_only_replaced_with_archive(catalog, setup, tmp_path):
    discord, game_dir, commit, _ = setup
    with pytest.raises(RuntimeError):
        start_game(catalog, game_dir, discord, CHANNEL, length="kurz", commit=commit, archive_root=tmp_path / "archive")
    start_game(catalog, game_dir, discord, CHANNEL, length="kurz", archive=True, commit=commit, seed="zwei",
               archive_root=tmp_path / "archive")
    archived = list((tmp_path / "archive").iterdir())
    assert len(archived) == 1 and (archived[0] / "state.json").exists()
    assert load_game(game_dir).game_id == "zwei"


def test_bot_and_ooc_messages_are_not_actions(catalog, setup):
    discord, game_dir, _, _ = setup
    state = load_game(game_dir)
    discord.send(CHANNEL, "Ich bin der Bot.")
    discord.user_message(CHANNEL, "11", "Lea", "//nur Gerede")
    discord.user_message(CHANNEL, "12", "Tom", "   ")
    texts, names, counted, newest = collect_texts(discord, CHANNEL, state)
    assert texts == {} and counted == []
    assert newest is not None


def test_split_text_respects_the_limit():
    text = "\n\n".join(["Ein Satz. " * 60] * 6)
    parts = split_text(text, 2000)
    assert all(len(p) <= 2000 for p in parts)
    assert sum(len(p) for p in parts) >= len(text.replace("\n\n", "")) * 0.9


# --- the real REST client against a mocked HTTP server ----------------------------


def rest_client(handler):
    client = httpx.Client(base_url="https://discord.com/api/v10", transport=httpx.MockTransport(handler))
    return DiscordREST("token", client=client)


def test_rest_reads_all_pages_oldest_first():
    pages = {None: [{"id": str(i)} for i in range(200, 100, -1)],  # newest first, like Discord
             "200": [{"id": "201"}]}

    def handler(request):
        after = request.url.params.get("after")
        if after == "100":
            return httpx.Response(200, json=pages[None])
        return httpx.Response(200, json=pages.get(after, []))

    messages = rest_client(handler).messages_after("1", "100")
    assert [m["id"] for m in messages][:2] == ["101", "102"]
    assert messages[-1]["id"] == "201"


def test_rest_waits_on_rate_limit_and_limits_mentions(monkeypatch):
    calls = []
    monkeypatch.setattr("time.sleep", lambda s: calls.append(("sleep", s)))

    def handler(request):
        calls.append(("call", request.method))
        if len([c for c in calls if c[0] == "call"]) == 1:
            return httpx.Response(429, json={"retry_after": 0.5})
        body = json.loads(request.content)
        assert body["allowed_mentions"] == {"parse": ["users"]}
        return httpx.Response(200, json={"id": "5"})

    message = rest_client(handler).send("1", "Hallo <@11>", mentions=True)
    assert message["id"] == "5"
    assert ("sleep", 0.6) in calls
