"""What a group sees at its location, as plain data for the LLM prompts."""

from __future__ import annotations

from .catalog import Catalog
from .models import Character
from .rules import character as ch
from .rules.enemies import EnemySpec, health_words, scaled_count
from .rules.items import display_name
from .state import GameState
from .world import attitude_label


def enemy_entries(catalog: Catalog, state: GameState, location_id: str, players: int) -> list[dict]:
    """Enemies at a location: the running fight, or the hostile encounter."""
    encounter = state.world.location(location_id).encounter
    if encounter is None or encounter.state != "feindlich":
        return []
    if encounter.live:
        return [{"id": e.id, "name": e.name, "zustand": health_words(e)} for e in encounter.live if e.hp > 0 and not e.fled]
    entries = []
    for spec in encounter.enemies:
        count = scaled_count(catalog, EnemySpec(spec.name, spec.tier, tuple(spec.elements), spec.count), players)
        for n in range(count):
            name = spec.name if count == 1 else f"{spec.name} {n + 1}"
            entries.append({"id": f"{spec.name.lower().replace(' ', '-')}-{n + 1}", "name": name, "zustand": "unverletzt"})
    return entries


def player_entry(catalog: Catalog, player: Character) -> dict:
    return {
        "id": player.id,
        "name": player.name,
        "klasse": player.class_label,
        "element": player.element,
        "stufe": player.level,
        "lp": f"{player.hp}/{ch.max_hp(catalog, player)}",
        "faehigkeiten": [
            {"id": a, "name": catalog.abilities[a].name, "bereit": ch.ability_ready(player, a)}
            for a in player.abilities
        ],
        "ausruestung": [
            {"id": item.id, "name": item.name, "platz": slot}
            for slot, item in vars(player.equipment).items() if item is not None
        ],
        "rucksack": [{"id": i.id, "name": display_name(catalog, i), "basis": i.base} for i in player.bag],
        "gold": player.gold,
        "grab_hier": player.grave is not None and player.grave.location == player.location,
    }


def scene(catalog: Catalog, state: GameState, location_id: str, players: list[Character]) -> dict:
    world = state.world
    loc = world.location(location_id)
    region = world.region_of(location_id)
    exits = []
    for con in world.visible_connections(location_id):
        target = world.location(con.to)
        exits.append({
            "id": con.to,
            "name": target.name,
            "bedingung": con.requirement.text if con.requirement and not con.opened else None,
        })
    npcs = []
    for npc in world.npcs_at(location_id):
        npcs.append({
            "id": npc.id, "name": npc.name, "rolle": npc.role, "haltung": attitude_label(npc.attitude),
            "angebot": [{"basis": b, "name": catalog.items[b].name} for b in npc.shop],
        })
    return {
        "ort": {
            "id": loc.id, "name": loc.name, "typ": loc.type, "region": region.name,
            "merkmale": [{"id": f.id, "name": f.name} for f in loc.features],
            "ausgaenge": exits,
            "gegenstaende_am_boden": [{"id": i.id, "name": i.name} for i in loc.items],
            "rastplatz": loc.rest_point,
        },
        "gegner": enemy_entries(catalog, state, location_id, len(players)),
        "kampf_laeuft": bool(loc.encounter and loc.encounter.live),
        "nsc": npcs,
        "spieler": [player_entry(catalog, p) for p in players],
    }
