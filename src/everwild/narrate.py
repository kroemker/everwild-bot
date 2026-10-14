"""Narrate: the executed outcome → German chapter text (design §18).

The LLM only decides *how* things are told. Without an LLM, a plain
template narrator strings the facts together, which is enough for testing.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from .catalog import Catalog
from .engine import GroupReport, TurnReport
from .interpret import prompt
from .llm import LLM, ask_model
from .rules import character as ch
from .state import GameState
from .world import attitude_label

MAX_MEMORY = 10


class NpcMemory(BaseModel):
    npc_id: str
    note: str


class Narration(BaseModel):
    text: str = Field(description="Der erzählte Abschnitt, 150–250 Wörter")
    npc_memories: list[NpcMemory] = Field(description="Notizen für NSC, mit denen gesprochen wurde")
    location_notes: list[str] = Field(description="Dauerhafte Veränderungen am Ort, meist leer")


def hp_words(catalog: Catalog, player) -> str:
    ratio = player.hp / ch.max_hp(catalog, player)
    if ratio >= 1:
        return "unverletzt"
    if ratio > 0.6:
        return "leicht verletzt"
    if ratio > 0.3:
        return "verletzt"
    return "schwer verletzt"


def _location(state: GameState, location_id: str) -> dict:
    loc = state.world.location(location_id)
    return {
        "name": loc.name,
        "beschreibung": loc.description,
        "stimmung": state.world.region_of(location_id).mood,
        "merkmale": [{"name": f.name, "beschreibung": f.description} for f in loc.features],
        "zustand": loc.state_notes,
    }


def narration_payload(catalog: Catalog, state: GameState, group: GroupReport) -> dict:
    world = state.world
    players = [state.players[p] for p in group.players if p in state.players]
    talks = []
    for talk in group.talks:
        npc = world.npcs[talk["npc"]]
        talks.append({
            "nsc": {"id": npc.id, "name": npc.name, "rolle": npc.role, "aussehen": npc.appearance,
                    "wesen": npc.personality, "sprechweise": npc.speech, "wissen": npc.knowledge,
                    "wuensche": npc.wants, "haltung": attitude_label(npc.attitude), "erinnerungen": npc.memory},
            "spieler": talk["spieler"], "sagt": talk["sagt"], "ueberzeugt": talk["ueberzeugt"],
        })
    payload = {
        "ort": _location(state, group.location),
        "gruppe": [{"name": p.name, "klasse": p.class_label, "element": p.element,
                    "hintergrund": p.background, "zustand": hp_words(catalog, p)} for p in players],
        "ereignisse": group.facts,
        "gespraeche": talks,
        "gegner_danach": group.enemies,
        "bisher": state.summary,
    }
    others = group.end_locations - {group.location}
    if others:
        payload["ziele"] = [_location(state, loc) for loc in sorted(others)]
    if group.questions:
        payload["erkenntnis"] = {
            "fragen": group.questions,
            "weltwissen": [world.premise]
            + [k for npc in world.npcs.values() for k in npc.knowledge]
            + [f"{loc.name}: {con.requirement.text}" for loc in world.locations.values()
               for con in loc.connections if con.requirement],
        }
    return payload


def narrate_group(catalog: Catalog, state: GameState, group: GroupReport, llm: LLM | None) -> str:
    if llm is None:
        group.narration = offline_narration(state, group)
        return group.narration
    payload = narration_payload(catalog, state, group)
    result = ask_model(llm, prompt("narrate"), json.dumps(payload, ensure_ascii=False, indent=1), Narration, max_tokens=3000)
    for memory in result.npc_memories:
        npc = state.world.npcs.get(memory.npc_id)
        if npc is not None:
            npc.memory = (npc.memory + [memory.note])[-MAX_MEMORY:]
    if result.location_notes:
        loc = state.world.location(group.location)
        loc.state_notes = (loc.state_notes + result.location_notes)[-MAX_MEMORY:]
    group.narration = result.text.strip()
    return group.narration


def offline_narration(state: GameState, group: GroupReport) -> str:
    """Plain text from the facts. Not pretty, but complete and honest."""
    ends = group.end_locations - {group.location}
    loc = state.world.location(next(iter(ends)) if len(ends) == 1 else group.location)
    first_sentence = loc.description.split(". ")[0].rstrip(".") + "."
    lines = [first_sentence]
    for fact in group.facts:
        lines.append(fact)
    for talk in group.talks:
        npc = state.world.npcs[talk["npc"]]
        told = sum(1 for m in npc.memory if m.startswith("erzählt:"))
        fact = npc.knowledge[told % len(npc.knowledge)] if npc.knowledge else "Darüber weiß ich nichts."
        npc.memory = (npc.memory + [f"erzählt: {fact}"])[-MAX_MEMORY:]
        lines.append(f"{npc.name} ({npc.speech.rstrip('.')}) antwortet {talk['spieler']}: „{fact}“")
    for question in group.questions:
        lines.append(f"Die Antwort auf „{question}“ liegt im Weltwissen: {state.world.premise}")
    return "\n\n".join(lines)


def update_summary(state: GameState, report: TurnReport, llm: LLM | None) -> None:
    chapters = "\n\n".join(g.narration for g in report.groups if g.narration)
    if not chapters:
        return
    if llm is None:
        facts = [f for g in report.groups for f in g.facts if not f.startswith("Kampf:")]
        state.summary = (state.summary + f" Tag {report.turn}: " + " ".join(facts[:6])).strip()[-1500:]
        return
    payload = f"Bisherige Zusammenfassung:\n{state.summary or '(noch keine)'}\n\nKapitel von Tag {report.turn}:\n{chapters}"
    state.summary = llm.text(prompt("summary"), payload, max_tokens=1500).strip()
