"""Whole turns with the offline interpreter on the test world."""

from pathlib import Path

import pytest

from everwild.engine import TurnEngine
from everwild.interpret import Interpreter
from everwild.narrate import narrate_group, update_summary
from everwild.play_local import DEFAULT_WORLD, new_game
from everwild.render import chapter_text, sheet_text
from everwild.rules import character as ch
from everwild.rules.dice import seeded_rng
from everwild.state import load_game, save_game


class Game:
    """The game state plus a helper to run a whole turn offline."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.state = new_game(DEFAULT_WORLD, "mittel", "test")

    def __getattr__(self, name):
        return getattr(self.state, name)

    def turn_fn(self, texts, seed=None):
        state = self.state
        rng = seeded_rng("test", seed if seed is not None else state.turn + 1)
        report = TurnEngine(self.catalog, state, rng, Interpreter()).run_turn(texts)
        for group in report.groups:
            narrate_group(self.catalog, state, group, None)
        update_summary(state, report, None)
        return report


@pytest.fixture
def game(catalog):
    return Game(catalog)


def join_two(game):
    game.turn_fn({"lea": "Ich bin Brakka, eine Kriegerin des Feuers.", "tom": "Ich heiße Mira, Klerikerin des Lichts."})
    return game.players["lea"], game.players["tom"]


def facts(report):
    return [f for g in report.groups for f in g.facts]


def test_join_creates_characters_at_start(game):
    brakka, mira = join_two(game)
    assert (brakka.name, brakka.class_id, brakka.element) == ("Brakka", "krieger", "feuer")
    assert (mira.name, mira.class_id, mira.class_label, mira.element) == ("Mira", "kleriker", "Klerikerin", "licht")
    assert brakka.location == mira.location == "dorf"


def test_unknown_class_joins_as_wanderer(game):
    report = game.turn_fn({"x": "Ich bin Glutzahn, ein Drache!"})
    assert game.players["x"].class_id == "wanderer"
    assert any("Wanderer" in note for note in report.ooc)


def test_chatter_from_non_players_is_ignored(game):
    game.turn_fn({"gast": "haha, viel Spaß euch"})
    assert "gast" not in game.players


def test_search_finds_hidden_quest_item(game):
    brakka, mira = join_two(game)
    for seed in range(20):
        game.turn_fn({"tom": "Ich untersuche den eingestürzten Glockenturm."}, seed=seed)
        if any(i.name == "Fährmannsmünze" for i in mira.bag):
            break
    assert any(i.name == "Fährmannsmünze" for i in mira.bag)
    assert game.world.location("dorf").features[1].searched


def test_threat_is_seen_on_arrival_and_fight_starts_next_turn(game):
    brakka, mira = join_two(game)
    report = game.turn_fn({"lea": "Ich gehe in den Finsterwald.", "tom": "Ich folge Brakka."})
    assert brakka.location == mira.location == "wald"
    assert game.world.location("wald").discovered
    assert any("lauert Gefahr" in f for f in facts(report))
    assert brakka.xp == 5  # new location
    report = game.turn_fn({"lea": "Ich greife den Grauwolf an!", "tom": "Ich kämpfe mit dem Streitkolben."})
    assert any(f.startswith("Kampf:") for f in facts(report))


def test_going_back_avoids_a_seen_threat(game):
    brakka, mira = join_two(game)
    game.turn_fn({"lea": "Ich gehe in den Finsterwald.", "tom": "Ich folge Brakka."})
    report = game.turn_fn({"lea": "Ich gehe zurück ins Dorf Dornbach.", "tom": "Ich folge Brakka."})
    assert brakka.location == mira.location == "dorf"
    assert not any(f.startswith("Kampf:") for f in facts(report))


def test_staying_after_a_seen_threat_starts_the_fight(game):
    join_two(game)
    game.turn_fn({"lea": "Ich gehe in den Finsterwald.", "tom": "Ich folge Brakka."})
    report = game.turn_fn({"lea": "Ich untersuche den Jägerstand.", "tom": "Ich raste."})
    assert any(f.startswith("Kampf:") for f in facts(report))
    assert any("keine Zeit" in f for f in facts(report))


def test_moving_on_past_a_seen_threat_needs_sneaking(game):
    brakka, _ = join_two(game)
    game.turn_fn({"lea": "Ich gehe in den Finsterwald.", "tom": "Ich folge Brakka."})
    report = game.turn_fn({"lea": "Ich gehe zum Schrein der Morgenröte.", "tom": "Ich folge Brakka."})
    assert any("vorbei" in f for f in facts(report))


def test_fight_until_victory_gives_xp_and_gold(game):
    brakka, mira = join_two(game)
    game.turn_fn({"lea": "Ich gehe zur alten Mühle.", "tom": "Ich folge Brakka."})
    for _ in range(4):
        if game.world.location("muehle").encounter.state == "besiegt":
            break
        game.turn_fn({"lea": "Ich greife die Riesenratte an!", "tom": "Ich greife an!"})
    assert game.world.location("muehle").encounter.state == "besiegt"
    assert brakka.xp >= 5 + 2 * 5
    assert brakka.gold + mira.gold > 20


def test_locked_path_needs_the_coin(game):
    brakka, _ = join_two(game)
    game.world.location("steg").encounter.state = "besiegt"
    brakka.location = "steg"
    report = game.turn_fn({"lea": "Ich gehe zum Hort des Sumpfkönigs."})
    assert brakka.location == "steg"
    assert any("Münze" in f for f in facts(report))
    from everwild.rules.items import add_to_bag, make_item
    add_to_bag(game_catalog(), brakka, make_item(game_catalog(), seeded_rng("x", 1), "questgegenstand", name="Fährmannsmünze"))
    game.turn_fn({"lea": "Ich gehe zum Hort des Sumpfkönigs."})
    assert brakka.location == "hort"


def game_catalog():
    from everwild.catalog import default_catalog
    return default_catalog()


def test_ambush_attacks_on_arrival(game):
    brakka, mira = join_two(game)
    game.world.location("wald").encounter.state = "besiegt"
    brakka.location = mira.location = "wald"
    report = game.turn_fn({"lea": "Ich gehe zum versunkenen Steg.", "tom": "Ich folge Brakka."})
    assert any("Hinterhalt" in f for f in facts(report))
    assert any(f.startswith("Kampf:") for f in facts(report))


def test_shrine_rest_raises_affinity_once(game):
    _, mira = join_two(game)
    mira.location = "schrein"
    game.turn_fn({"tom": "Ich raste und bete am Altar."})
    assert mira.affinity["licht"] == 2
    game.turn_fn({"tom": "Ich raste."})
    assert mira.affinity["licht"] == 2
    assert mira.last_rest_point == "schrein"


def test_buy_and_give(game):
    brakka, mira = join_two(game)
    gold = brakka.gold
    game.turn_fn({"lea": "Ich kaufe bei Hedda einen Heiltrank."})
    assert brakka.gold < gold
    potions = sum(i.quantity for i in brakka.bag if i.base == "heiltrank")
    assert potions == 2
    game.turn_fn({"lea": "Ich gebe Mira einen Heiltrank."})
    assert sum(i.quantity for i in mira.bag if i.base == "heiltrank") >= 2


def test_idle_players_go_to_camp_and_come_back(game):
    brakka, mira = join_two(game)
    for _ in range(3):
        game.turn_fn({"lea": "Ich raste."})
    assert mira.status == "camp"
    report = game.turn_fn({"tom": "Ich raste."})
    assert mira.status == "active"
    assert any("kehrt aus dem Lager zurück" in note for note in report.ooc)


def test_idle_member_follows_the_group(game):
    brakka, mira = join_two(game)
    game.turn_fn({"lea": "Ich gehe zur alten Mühle."})
    assert mira.location == "muehle"


def test_death_leaves_a_grave(game, catalog):
    brakka, mira = join_two(game)
    mira.status = "left"
    brakka.location = "hort"
    brakka.gold = 20
    for _ in range(6):
        game.turn_fn({"lea": "Ich greife den Sumpfkönig an!"})
        if brakka.grave:
            break
    assert brakka.grave is not None and brakka.grave.location == "hort"
    assert brakka.location == "dorf"
    assert brakka.hp == ch.max_hp(catalog, brakka)


def test_chapter_and_sheet_render(game, catalog):
    brakka, _ = join_two(game)
    report = game.turn_fn({"lea": "Ich spreche mit Hedda."})
    text = chapter_text(catalog, game.state, report)
    assert text.startswith("## ☀️ Tag 2") and "@Brakka" in text and "Ergebnis" in text
    sheet = sheet_text(catalog, game.state, brakka)
    assert "Rüstungswert 14" in sheet and "Wuchtschlag ✔" in sheet


def test_save_and_load_round_trip(game, tmp_path: Path):
    join_two(game)
    game.turn_fn({"lea": "Ich gehe in den Finsterwald."})
    save_game(game.state, tmp_path)
    loaded = load_game(tmp_path)
    assert loaded.turn == game.turn
    assert loaded.players["lea"].location == "wald"
    assert loaded.world.location("wald").discovered
