"""Many random days with random actions: nothing may crash, state stays valid."""

import random

import pytest

from everwild.engine import TurnEngine
from everwild.interpret import Interpreter
from everwild.narrate import narrate_group, update_summary
from everwild.play_local import DEFAULT_WORLD, new_game
from everwild.render import chapter_text, map_text, sheet_text
from everwild.rules import character as ch
from everwild.rules.dice import seeded_rng
from everwild.rules.items import slots_used

SENTENCES = [
    "Ich gehe in den Finsterwald.", "Ich gehe zur alten Mühle.", "Ich gehe zurück ins Dorf Dornbach.",
    "Ich gehe zum Schrein der Morgenröte.", "Ich gehe zum versunkenen Steg.", "Ich gehe zur Kate der Moorhexe.",
    "Ich gehe zum Hort des Sumpfkönigs.", "Ich gehe zur verborgenen Lichtung.",
    "Ich greife an!", "Ich greife den Grauwolf an.", "Ich setze Wuchtschlag ein.", "Ich wirke Heilung auf Mira.",
    "Ich verteidige Mira.", "Ich trinke einen Heiltrank.", "Ich fliehe!", "Ich raste.",
    "Ich untersuche die umgestürzte Eiche.", "Ich durchsuche den Steinkreis.", "Ich untersuche die Bronzefigur des Fährmanns.",
    "Ich spreche mit Hedda.", "Ich frage Grizzelda nach dem Sumpfkönig.", "Ich kaufe einen Heiltrank.",
    "Ich verkaufe den Dolch.", "Ich gebe Mira einen Heiltrank.", "Ich folge Brakka.", "Ich klettere auf den Jägerstand.",
    "Ich berge mein Grab.", "Ich hebe alles auf.", "", "", "Hmm, keine Ahnung.",
]


@pytest.mark.parametrize("seed", range(6))
def test_random_campaign(catalog, seed):
    rng = random.Random(seed)
    state = new_game(DEFAULT_WORLD, "kurz", f"fuzz{seed}")
    joins = {"lea": "Ich bin Brakka, eine Kriegerin des Feuers.", "tom": "Ich heiße Mira, Klerikerin des Lichts.",
             "kim": "Ich bin Fenn, ein Schurke der Schatten."}
    for day in range(40):
        texts = joins if day == 0 else {pid: rng.choice(SENTENCES) for pid in joins}
        texts = {pid: t for pid, t in texts.items() if t}
        if day == 20:
            texts["neu"] = "Ich bin Sólveig, eine Magierin der Luft."
        report = TurnEngine(catalog, state, seeded_rng(state.game_id, day), Interpreter()).run_turn(texts)
        for group in report.groups:
            narrate_group(catalog, state, group, None)
        update_summary(state, report, None)
        chapter_text(catalog, state, report)
        map_text(state)
        for player in state.players.values():
            sheet_text(catalog, state, player)
            assert 0 <= player.hp <= ch.max_hp(catalog, player)
            assert slots_used(catalog, player) <= catalog.rules.bag_slots
            assert player.location in state.world.locations
            assert player.gold >= 0
    assert state.turn == 40
