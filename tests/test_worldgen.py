"""World generation, quests, the seal and a complete campaign."""

import pytest

from everwild.actions import Action
from everwild.engine import TurnEngine
from everwild.interpret import Interpreter, JoinReply
from everwild.narrate import epilogue, narrate_group
from everwild.render import quest_log_text, stats_text
from everwild.rules import character as ch
from everwild.rules.dice import seeded_rng
from everwild.state import GameState
from everwild.worldgen import (
    PLACEHOLDER, RegionNaming, apply_region_naming, build_skeleton, check_solvable, finalize, generate_world,
    name_offline, region_request,
)


@pytest.mark.parametrize("length", ["kurz", "mittel", "lang"])
@pytest.mark.parametrize("seed", range(4))
def test_generated_worlds_are_valid_and_winnable(catalog, length, seed):
    world = generate_world(catalog, length, seeded_rng("welt", seed, length))
    settings = catalog.rules.game_lengths[length]
    element_regions = [r for r in world.regions.values() if r.id.startswith("r")]
    assert len(element_regions) == settings.regions
    assert world.shards_needed == settings.shards_needed
    assert check_solvable(world) == []
    # every region has a different set of elements, and none uses two opposites
    sets = [tuple(r.elements) for r in element_regions]
    assert len(set(sets)) == len(sets)
    for elements in sets:
        assert len(elements) == 1 or catalog.rules.elements[elements[0]].opposite != elements[1]
    # no placeholder left anywhere
    assert PLACEHOLDER not in world.model_dump_json()


def test_hints_match_the_structure(catalog):
    world = generate_world(catalog, "mittel", seeded_rng("welt", 1))
    for region in [r for r in world.regions if r.startswith("r")]:
        lock = next(c for c in world.locations[f"{region}-verlies"].connections if c.to == f"{region}-hort")
        key = next(f.hidden_item.name for f in world.locations[f"{region}-verlies"].features if f.hidden_item)
        assert lock.requirement.item_name == key
        sage = world.npcs[f"{region}-kundige"]
        assert any(key in fact for fact in sage.knowledge)
        assert world.quests[f"q-{region}"].steps[1].item_name == key


def test_a_broken_world_is_reported(catalog):
    world, plans = build_skeleton(catalog, "kurz", seeded_rng("welt", 2))
    name_offline(world, plans, seeded_rng("welt", 2))
    finalize(world, plans)
    world.locations["r0-verlies"].features[1].hidden_item = None  # the key disappears
    assert any("Splitter" in p or "erreichbar" in p.lower() for p in check_solvable(world))


def test_llm_names_are_applied_by_id(catalog):
    world, plans = build_skeleton(catalog, "kurz", seeded_rng("welt", 3))
    name_offline(world, plans, seeded_rng("welt", 3))
    plan = plans[1]
    request = region_request(world, plan, "Inselwelt")
    first_loc = request["orte"][0]
    naming = RegionNaming(
        name="Die Salzinseln", mood="Gischt und Möwen.", people_name="Salzvolk", people_description="Fischer.",
        locations=[{"id": first_loc["id"], "name": "Klippe der Möwen", "description": "Weiße Felsen.",
                    "features": [{"id": first_loc["merkmale"][0], "name": "Zerbrochener Mast", "description": "Morsch."}]},
                   {"id": "gibt-es-nicht", "name": "X", "description": "Y", "features": []}],
        npcs=[{"id": request["nsc"][0]["id"], "name": "Kapitänin Meeke", "appearance": "Wettergegerbt.",
               "personality": "Rau.", "speech": "Spricht nur in Seemannsgarn.", "wants": "Ihr Schiff."}],
        creatures=[{"id": request["kreaturen"][0]["id"], "name": "Salzkrebs", "description": "Klackernde Scheren."}],
        key_item="Muschelschlüssel", side_item="Kompass", quest_names=["Das Herz der Inseln"],
    )
    apply_region_naming(world, plan, naming)
    finalize(world, plans)
    assert world.regions[plan.id].name == "Die Salzinseln"
    assert world.locations[first_loc["id"]].name == "Klippe der Möwen"
    assert world.npcs[request["nsc"][0]["id"]].name == "Kapitänin Meeke"
    assert world.quests[plan.main_quest].name == "Das Herz der Inseln"
    assert any("Muschelschlüssel" in fact for fact in world.npcs[plan.npcs["kundige"]].knowledge)
    assert check_solvable(world) == []


class ScriptedInterpreter(Interpreter):
    """Returns prepared actions instead of reading text."""

    script: dict = {}

    def actions(self, catalog, scene, texts):
        return [self.script.get(pid) or Action(player_id=pid, kind="nichts") for pid in texts]

    def join(self, catalog, text):
        name, class_id = text.split(":")
        return JoinReply(is_join=True, name=name, class_id=class_id, class_label=None, element="feuer", background=None)


def test_complete_campaign(catalog):
    """Three veterans play a short world from the intro to the epilogue."""
    world = generate_world(catalog, "kurz", seeded_rng("kampagne", 0))
    state = GameState(game_id="kampagne", length="kurz", world=world)
    interpreter = ScriptedInterpreter()
    heroes = {"a": "Brakka:krieger", "b": "Mira:kleriker", "c": "Fenn:schurke"}

    def turn(actions: dict[str, Action] | None = None, texts=None):
        interpreter.script = actions or {}
        engine = TurnEngine(catalog, state, seeded_rng("kampagne", state.turn + 1), interpreter)
        report = engine.run_turn(texts or {pid: "…" for pid in heroes})
        for group in report.groups:
            narrate_group(catalog, state, group, None)
        return report

    turn(texts=heroes)
    for hero in state.players.values():
        ch.set_xp(catalog, hero, ch.level_start_xp(catalog, 10, "kurz"), "kurz")
        hero.hp = ch.max_hp(catalog, hero)
        for item in (hero.equipment.waffe, hero.equipment.ruestung):
            item.rarity = "selten"

    def everyone(kind, **kw):
        return {pid: Action(player_id=pid, kind=kind, **kw) for pid in heroes}

    def place(location):
        for hero in state.players.values():
            hero.location = hero.previous_location = location
            world.locations[location].discovered = True

    def rest_up():
        """What a sensible group does before a fight: rest at a rest point."""
        for hero in state.players.values():
            hero.hp, hero.down = ch.max_hp(catalog, hero), False

    def fight_at(location):
        rest_up()
        place(location)
        for _ in range(25):
            if world.locations[location].encounter.state != "feindlich":
                return
            # plain attacks only; healing between days stands in for real tactics
            # (whether fights are winnable is the balancing simulation's job)
            rest_up()
            for hero in state.players.values():
                hero.location = location
            last = turn(everyone("angreifen"))
        raise AssertionError(f"Kampf in {location} nicht gewonnen: {[f for g in last.groups for f in g.facts]}")

    # intro quest
    elder = "s-aelteste"
    turn(everyone("sprechen", target=elder, speech="Was ist geschehen?"))
    fight_at("s-feld")
    place("s-dorf")
    turn(everyone("sprechen", target=elder, speech="Die Wesen sind fort."))
    assert world.quests["q-start"].done

    # every region: ask the sage, find the key, beat the boss
    for region in [r for r in world.regions if r.startswith("r")]:
        place(f"{region}-siedlung")
        turn(everyone("sprechen", target=f"{region}-kundige", speech="Wo ist der Herr dieser Lande?"))
        fight_at(f"{region}-verlies")
        key_feature = next(f for f in world.locations[f"{region}-verlies"].features if f.hidden_item)
        for _ in range(10):
            if key_feature.searched:
                break
            place(f"{region}-verlies")
            turn(everyone("untersuchen", target=key_feature.id))
        assert key_feature.searched
        place(f"{region}-verlies")
        moved = turn(everyone("bewegen", target=f"{region}-hort"))
        assert all(h.location == f"{region}-hort" for h in state.players.values()), [f for g in moved.groups for f in g.facts]
        assert all(h.location == f"{region}-hort" for h in state.players.values())
        fight_at(f"{region}-hort")
        assert world.quests[f"q-{region}"].done

    assert len(set(world.seal)) == world.shards_needed
    report = turn({})
    assert report.announcements  # the shards call everyone to the final area
    assert all(h.location == world.final_rest for h in state.players.values())

    fight_at(world.final_location)
    assert state.finished
    log = quest_log_text(catalog, state)
    assert "✅" in log
    assert "Epilog" in epilogue(catalog, state, None)
    stats = stats_text(state)
    assert "besiegten Gegner" in stats
