"""The LLM path, with a fake model instead of OpenAI."""

import json

import pytest

from everwild.actions import ActionList, strict_schema
from everwild.engine import TurnEngine
from everwild.interpret import Interpreter, JoinReply
from everwild.llm import ask_model
from everwild.narrate import Narration, narrate_group
from everwild.play_local import DEFAULT_WORLD, new_game
from everwild.rules.dice import seeded_rng


class FakeLLM:
    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def json(self, system, prompt, schema, schema_name, max_tokens=4000):
        self.calls.append((schema_name, prompt))
        reply = self.replies.pop(0)
        return reply(prompt) if callable(reply) else reply

    def text(self, system, prompt, max_tokens=2000):
        self.calls.append(("text", prompt))
        return "Zusammenfassung."


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


@pytest.mark.parametrize("model", [ActionList, JoinReply, Narration])
def test_strict_schema_rules(model):
    schema = strict_schema(model)
    for node in walk(schema):
        assert "default" not in node
        if "$ref" in node:
            assert list(node) == ["$ref"]
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_ask_model_retries_with_the_error():
    llm = FakeLLM(['{"actions": [{"player_id": "a"}]}', '{"actions": []}'])
    result = ask_model(llm, "system", "prompt", ActionList)
    assert result.actions == []
    assert "ungültig" in llm.calls[1][1]


def test_ask_model_gives_up_after_retries():
    llm = FakeLLM(["kein json"] * 3)
    with pytest.raises(RuntimeError):
        ask_model(llm, "system", "prompt", ActionList)


def empty_action(pid, **kw):
    action = {"player_id": pid, "kind": "nichts", "target": None, "ability": None, "item": None, "speech": None,
              "attribute": None, "difficulty": None, "equip": [], "summary": "", "join": None, "new_class": None,
              "new_element": None, "ability_choice": None, "attribute_choice": None, "leave": False}
    action.update(kw)
    return action


def test_turn_with_llm_join_interpret_and_narration(catalog):
    state = new_game(DEFAULT_WORLD, "mittel", "llm")
    join = json.dumps({"is_join": True, "name": "Brakka", "class_id": "krieger", "class_label": "Kriegerin",
                       "element": "feuer", "background": "Eine Söldnerin aus dem Norden."})
    talk = json.dumps({"actions": [empty_action("lea", kind="sprechen", target="hedda", speech="Was gibt es Neues?")]})
    narration = json.dumps({"text": "**Brakka** betritt den Platz …", "location_notes": [],
                            "npc_memories": [{"npc_id": "hedda", "note": "Brakka hat nach Neuigkeiten gefragt."}]})
    llm = FakeLLM([join, talk, narration])
    engine = TurnEngine(catalog, state, seeded_rng("llm", 1), Interpreter(llm=llm))
    report = engine.run_turn({"lea": "Ich bin Brakka, Kriegerin des Feuers. Was gibt es Neues, Hedda?"})
    assert state.players["lea"].class_label == "Kriegerin"
    group = report.groups[0]
    assert group.talks and group.talks[0]["npc"] == "hedda"
    narrate_group(catalog, state, group, llm)
    assert group.narration.startswith("**Brakka**")
    assert state.world.npcs["hedda"].memory[-1] == "Brakka hat nach Neuigkeiten gefragt."
    # the interpret prompt only offers ids from the scene
    interpret_prompt = json.loads(llm.calls[1][1])
    assert {n["id"] for n in interpret_prompt["szene"]["nsc"]} == {"hedda", "ilsabe"}
