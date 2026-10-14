"""World generation (design §11, §13, §15).

1. ``build_skeleton``: Python builds regions, locations, paths, locks,
   encounters, quests and the finale, with placeholder names.
2. Naming: the LLM (``name_with_llm``) or the offline word lists
   (``name_offline``) give everything names and descriptions.
3. ``finalize``: Python writes NPC knowledge, lock texts and quest texts from
   the final names, so hints always match the structure.
4. ``check_solvable``: the game must be winnable before anything is posted.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from .catalog import DEFAULT_CATALOG_DIR, Catalog
from .models import Element, Tier
from .world import (
    NPC, Connection, Encounter, EnemyEntry, Feature, ItemSpec, Location, People, Quest, QuestStep, Region,
    Requirement, Reward, World,
)

ELEMENTS: list[Element] = ["feuer", "wasser", "erde", "luft", "licht", "schatten"]
OPPOSITE = {"feuer": "wasser", "wasser": "feuer", "erde": "luft", "luft": "erde", "licht": "schatten", "schatten": "licht"}
ENCOUNTERS: dict[str, list[tuple[Tier, int]]] = {
    "leicht": [("schwach", 2)],
    "standard": [("normal", 1), ("schwach", 1)],
    "hart": [("stark", 1), ("normal", 1)],
    "elite": [("elite", 1), ("normal", 1)],
    "boss": [("boss", 1)],
}
PLACEHOLDER = "?"


@lru_cache(maxsize=1)
def words() -> dict:
    return json.loads((DEFAULT_CATALOG_DIR / "worldgen.json").read_text(encoding="utf-8"))


@dataclass
class RegionPlan:
    """Which location plays which role; used by naming and ``finalize``."""

    id: str
    kind: str  # start, element, final
    elements: list[Element]
    level: int
    tier: int = 0
    roles: dict[str, str] = field(default_factory=dict)  # role -> location id
    npcs: dict[str, str] = field(default_factory=dict)  # role -> npc id
    key_feature: tuple[str, str] | None = None  # (location, feature) hiding the key item
    side_feature: tuple[str, str] | None = None
    main_quest: str | None = None
    side_quests: list[str] = field(default_factory=list)


# --- 1. skeleton ---------------------------------------------------------------


def _region_elements(rng: random.Random, count: int) -> tuple[list[list[Element]], list[Element]]:
    final_pair = list(rng.choice([("feuer", "wasser"), ("erde", "luft"), ("licht", "schatten")]))
    options: list[list[Element]] = [[e] for e in ELEMENTS]
    options += [[a, b] for i, a in enumerate(ELEMENTS) for b in ELEMENTS[i + 1:] if OPPOSITE[a] != b]
    rng.shuffle(options)
    chosen: list[list[Element]] = []
    primaries: set[str] = set()
    for option in options:  # prefer a new primary element for every region
        if option[0] not in primaries:
            chosen.append(option)
            primaries.add(option[0])
        if len(chosen) == count:
            break
    for option in options:
        if len(chosen) == count:
            break
        if option not in chosen:
            chosen.append(option)
    return chosen, final_pair  # type: ignore[return-value]


def _encounter(kind: str, elements: list[Element], **extra) -> Encounter:
    entries = [EnemyEntry(name=PLACEHOLDER, tier=tier, elements=list(elements), count=count) for tier, count in ENCOUNTERS[kind]]
    return Encounter(enemies=entries, **extra)


def _features(location_id: str, count: int = 3) -> list[Feature]:
    return [Feature(id=f"{location_id}-m{n + 1}", name=PLACEHOLDER) for n in range(count)]


def _location(world: World, location_id: str, region: str, type_: str, **extra) -> Location:
    loc = Location(id=location_id, name=PLACEHOLDER, region=region, type=type_, description=PLACEHOLDER,  # type: ignore[arg-type]
                   features=_features(location_id), **extra)
    world.locations[location_id] = loc
    return loc


def _connect(world: World, a: str, b: str, requirement: Requirement | None = None, hidden: bool = False) -> None:
    """Two-way path. A requirement only applies on the way from a to b."""
    world.locations[a].connections.append(Connection(to=b, requirement=requirement, hidden=hidden))
    world.locations[b].connections.append(Connection(to=a))


def _npc(world: World, npc_id: str, location: str, role: str, people: str | None, **extra) -> NPC:
    npc = NPC(id=npc_id, name=PLACEHOLDER, people=people, location=location, role=role,
              appearance=PLACEHOLDER, personality=PLACEHOLDER, speech=PLACEHOLDER, **extra)
    world.npcs[npc_id] = npc
    world.locations[location].npcs.append(npc_id)
    return npc


def _levels(count: int) -> list[int]:
    if count == 1:
        return [2]
    return [2 + round(i * 7 / (count - 1)) for i in range(count)]


def build_skeleton(catalog: Catalog, length: str, rng: random.Random) -> tuple[World, list[RegionPlan]]:
    settings = catalog.rules.game_lengths[length]
    world = World(name=PLACEHOLDER, premise=PLACEHOLDER, start_location="s-dorf", regions={}, locations={},
                  shards_needed=settings.shards_needed)
    plans: list[RegionPlan] = []

    # start region: village, an easy first fight, a quiet road to the gate
    start = RegionPlan(id="start", kind="start", elements=[], level=1)
    world.regions["start"] = Region(id="start", name=PLACEHOLDER, elements=[], level=1, mood=PLACEHOLDER)
    world.peoples["volk-start"] = People(id="volk-start", name=PLACEHOLDER, elements=[], description=PLACEHOLDER)
    _location(world, "s-dorf", "start", "siedlung", rest_point=True, inn=True, discovered=True)
    _location(world, "s-feld", "start", "wildnis", encounter=_encounter("leicht", []))
    _location(world, "s-weg", "start", "wildnis")
    _connect(world, "s-dorf", "s-feld")
    _connect(world, "s-dorf", "s-weg")
    start.roles = {"siedlung": "s-dorf", "wildnis": "s-feld", "weg": "s-weg"}
    _npc(world, "s-aelteste", "s-dorf", "Älteste des Dorfes", "volk-start", indispensable=True)
    _npc(world, "s-haendler", "s-dorf", "Händler", "volk-start", shop=["heiltrank", "dolch", "schild", "lederruestung", "elementoel"])
    start.npcs = {"aelteste": "s-aelteste", "haendler": "s-haendler"}
    intro = Quest(id="q-start", name=PLACEHOLDER, kind="haupt", region="start", giver="s-aelteste", known=True, steps=[
        QuestStep(id="q-start-1", text=PLACEHOLDER, kind="talk", npc="s-aelteste"),
        QuestStep(id="q-start-2", text=PLACEHOLDER, kind="defeat", location="s-feld"),
        QuestStep(id="q-start-3", text=PLACEHOLDER, kind="talk", npc="s-aelteste"),
    ])
    world.quests[intro.id] = intro
    start.main_quest = intro.id
    plans.append(start)

    # element regions in tiers of two; each tier needs one more shard
    element_sets, final_pair = _region_elements(rng, settings.regions)
    levels = _levels(settings.regions)
    for index, elements in enumerate(element_sets):
        rid = f"r{index}"
        plan = RegionPlan(id=rid, kind="element", elements=elements, level=levels[index], tier=index // 2)
        world.regions[rid] = Region(id=rid, name=PLACEHOLDER, elements=elements, level=plan.level, mood=PLACEHOLDER)
        people = f"volk-{rid}"
        world.peoples[people] = People(id=people, name=PLACEHOLDER, elements=elements, description=PLACEHOLDER,
                                       attitude=rng.choice([-1, 0, 0, 1]))
        late = plan.tier >= 1
        ids = {role: f"{rid}-{role}" for role in ("eingang", "siedlung", "wildnis", "verlies", "hort")}
        _location(world, ids["eingang"], rid, "wildnis", encounter=_encounter("standard", elements))
        _location(world, ids["siedlung"], rid, "siedlung", rest_point=True, inn=index % 2 == 0)
        _location(world, ids["wildnis"], rid, "wildnis", encounter=_encounter("hart" if late else "standard", elements))
        _location(world, ids["verlies"], rid, "dungeon", encounter=_encounter("elite" if late else "hart", elements))
        _location(world, ids["hort"], rid, "hort", encounter=_encounter("boss", elements, shard=elements[0]))
        _connect(world, ids["eingang"], ids["siedlung"])
        _connect(world, ids["siedlung"], ids["wildnis"])
        _connect(world, ids["wildnis"], ids["verlies"])
        _connect(world, ids["verlies"], ids["hort"], Requirement(kind="item", item_base="questgegenstand", text=PLACEHOLDER))
        plan.roles = dict(ids)
        # a hidden shrine of the region's element behind the wilderness
        shrine = f"{rid}-schrein"
        _location(world, shrine, rid, "schrein", rest_point=True, shrine_element=elements[0])
        _connect(world, ids["wildnis"], shrine, hidden=True)
        world.locations[ids["wildnis"]].features[0].hidden_path = shrine
        world.locations[ids["wildnis"]].features[0].search_difficulty = "mittel"
        plan.roles["schrein"] = shrine

        # the key to the boss lair lies hidden in the dungeon
        key_feature = world.locations[ids["verlies"]].features[1]
        key_feature.hidden_item = ItemSpec(base="questgegenstand", name=PLACEHOLDER)
        key_feature.search_difficulty = "mittel"
        plan.key_feature = (ids["verlies"], key_feature.id)

        settlement = ids["siedlung"]
        _npc(world, f"{rid}-kundige", settlement, "Kundige", people)
        _npc(world, f"{rid}-haendler", settlement, "Händler", people, shop=_shop(rng, elements))
        _npc(world, f"{rid}-bittsteller", settlement, "Bittsteller", people)
        plan.npcs = {"kundige": f"{rid}-kundige", "haendler": f"{rid}-haendler", "bittsteller": f"{rid}-bittsteller"}

        main = Quest(id=f"q-{rid}", name=PLACEHOLDER, kind="haupt", region=rid, steps=[
            QuestStep(id=f"q-{rid}-1", text=PLACEHOLDER, kind="talk", npc=f"{rid}-kundige"),
            QuestStep(id=f"q-{rid}-2", text=PLACEHOLDER, kind="item", item_name=PLACEHOLDER),
            QuestStep(id=f"q-{rid}-3", text=PLACEHOLDER, kind="defeat", location=ids["hort"]),
        ])
        world.quests[main.id] = main
        plan.main_quest = main.id

        side_feature = world.locations[ids["eingang"]].features[2]
        side_feature.hidden_item = ItemSpec(base="questgegenstand", name=PLACEHOLDER)
        side_feature.search_difficulty = "leicht"
        plan.side_feature = (ids["eingang"], side_feature.id)
        fetch = Quest(id=f"q-{rid}-a", name=PLACEHOLDER, kind="neben", region=rid, giver=f"{rid}-bittsteller",
                      reward=Reward(gold=15 * plan.level, people=people), steps=[
                          QuestStep(id=f"q-{rid}-a-1", text=PLACEHOLDER, kind="item", item_name=PLACEHOLDER),
                          QuestStep(id=f"q-{rid}-a-2", text=PLACEHOLDER, kind="deliver", npc=f"{rid}-bittsteller",
                                    item_name=PLACEHOLDER),
                      ])
        hunt = Quest(id=f"q-{rid}-b", name=PLACEHOLDER, kind="neben", region=rid, giver=f"{rid}-kundige",
                     reward=Reward(gold=10 * plan.level, affinity=elements[0]), steps=[
                         QuestStep(id=f"q-{rid}-b-1", text=PLACEHOLDER, kind="defeat", location=ids["wildnis"]),
                     ])
        world.quests[fetch.id] = fetch
        world.quests[hunt.id] = hunt
        plan.side_quests = [fetch.id, hunt.id]
        plans.append(plan)

    # paths between regions: tier 0 from the start region, later tiers from earlier regions
    element_plans = [p for p in plans if p.kind == "element"]
    for plan in element_plans:
        entry = plan.roles["eingang"]
        if plan.tier == 0:
            origin = "s-feld" if plan.id == "r0" else "s-weg"
            _connect(world, origin, entry)
        else:
            earlier = [p for p in element_plans if p.tier == plan.tier - 1]
            origin_plan = earlier[int(plan.id[1:]) % len(earlier)]
            _connect(world, origin_plan.roles["siedlung"], entry,
                     Requirement(kind="shards", count=plan.tier, text=PLACEHOLDER))

    # the final area behind the gate
    final = RegionPlan(id="final", kind="final", elements=final_pair, level=10)
    world.regions["final"] = Region(id="final", name=PLACEHOLDER, elements=final_pair, level=10, mood=PLACEHOLDER)
    _location(world, "f-vorhof", "final", "schrein", rest_point=True)
    phases = [final_pair[0], final_pair[1], rng.choice([e for e in ELEMENTS if e not in final_pair])]
    phase_count = 2 if length == "kurz" else 3
    boss = Encounter(enemies=[EnemyEntry(name=PLACEHOLDER, tier="boss", elements=[phases[0]])],
                     phases=[[EnemyEntry(name=PLACEHOLDER, tier="boss", elements=[e])] for e in phases[1:phase_count]])
    _location(world, "f-thron", "final", "hort", encounter=boss)
    _connect(world, "s-weg", "f-vorhof", Requirement(kind="shards", count=settings.shards_needed, text=PLACEHOLDER))
    _connect(world, "f-vorhof", "f-thron")
    final.roles = {"vorhof": "f-vorhof", "thron": "f-thron"}
    world.final_rest, world.final_location = "f-vorhof", "f-thron"
    plans.append(final)
    return world, plans


def _shop(rng: random.Random, elements: list[Element]) -> list[str]:
    stock = ["heiltrank", "elementoel"]
    stock += rng.sample(["schwert", "rapier", "streitkolben", "bogen", "stab", "kettenhemd", "schild", "talisman", "schriftrolle"], 3)
    return stock


# --- 2. naming -------------------------------------------------------------------


class NamedFeature(BaseModel):
    id: str
    name: str
    description: str


class NamedLocation(BaseModel):
    id: str
    name: str
    description: str = Field(description="3–5 Sätze, fest, wie der Ort aussieht")
    features: list[NamedFeature]


class NamedNPC(BaseModel):
    id: str
    name: str
    appearance: str
    personality: str
    speech: str = Field(description="Sprechweise; manche NSC dürfen komisch sein")
    wants: str


class NamedCreature(BaseModel):
    id: str
    name: str = Field(description="Name der Kreatur, ohne Nummer")
    description: str


class RegionNaming(BaseModel):
    name: str
    mood: str = Field(description="3–4 Sätze: Landschaft, Farben, Licht, Wetter, Geräusche, Gerüche")
    people_name: str
    people_description: str
    locations: list[NamedLocation]
    npcs: list[NamedNPC]
    creatures: list[NamedCreature]
    key_item: str = Field(description="Name des Schlüsselgegenstands zum Hort, leer wenn keiner gefragt")
    side_item: str = Field(description="Name des verlorenen Gegenstands für den Nebenauftrag, leer wenn keiner")
    quest_names: list[str] = Field(description="Namen der Aufträge in der Reihenfolge der Anfrage")


class WorldNaming(BaseModel):
    name: str
    premise: str = Field(description="2–3 Sätze: die Bedrohung und warum die Splitter zum Siegel müssen")
    final_bosses: list[str] = Field(description="Ein Name je Phase des Endgegners")


def _creature_slots(world: World, plan: RegionPlan) -> list[tuple[str, Location, int]]:
    slots = []
    for loc in world.locations.values():
        if loc.region != plan.id or loc.encounter is None:
            continue
        for n in range(len(loc.encounter.enemies)):
            slots.append((f"{loc.id}#{n}", loc, n))
        for p, phase in enumerate(loc.encounter.phases):
            slots.append((f"{loc.id}#p{p + 1}", loc, -(p + 1)))
    return slots


def region_request(world: World, plan: RegionPlan, theme: str) -> dict:
    locations = []
    for loc in world.locations.values():
        if loc.region != plan.id:
            continue
        hints = []
        for feature in loc.features:
            if feature.hidden_item:
                hints.append(f"{feature.id}: hier ist etwas versteckt")
            if feature.hidden_path:
                hints.append(f"{feature.id}: verbirgt einen geheimen Pfad")
        locations.append({"id": loc.id, "typ": loc.type, "rastplatz": loc.rest_point, "gasthaus": loc.inn,
                          "schrein_element": loc.shrine_element, "merkmale": [f.id for f in loc.features], "hinweise": hints})
    creatures = [{"id": slot, "stufe": (loc.encounter.enemies[n].tier if n >= 0 else "boss"),
                  "elemente": loc.encounter.enemies[n].elements if n >= 0 else loc.encounter.phases[-n - 1][0].elements,
                  "ort": loc.id} for slot, loc, n in _creature_slots(world, plan)]
    quests = [world.quests[q] for q in ([plan.main_quest] if plan.main_quest else []) + plan.side_quests]
    return {
        "thema": theme or "klassische High Fantasy",
        "welt": {"name": world.name, "praemisse": world.premise},
        "region": {"id": plan.id, "art": plan.kind, "elemente": plan.elements, "stufe": plan.level},
        "orte": locations,
        "nsc": [{"id": world.npcs[n].id, "rolle": world.npcs[n].role} for n in plan.npcs.values()],
        "kreaturen": creatures,
        "schluesselgegenstand": plan.key_feature is not None,
        "nebengegenstand": plan.side_feature is not None,
        "auftraege": [{"art": q.kind, "schritte": [s.kind for s in q.steps]} for q in quests],
    }


def name_offline(world: World, plans: list[RegionPlan], rng: random.Random) -> None:
    w = words()
    world.name = rng.choice(w["world_names"])
    world.premise = rng.choice(w["premises"])
    used_settlements = rng.sample(w["settlements"], len(w["settlements"]))
    used_names: set[str] = set()
    people_names = ["Talvolk", "Hügelvolk", "Moorvolk", "Felsvolk", "Windvolk", "Sonnenvolk", "Schattenvolk", "Glutvolk", "Eisvolk"]

    def pick(options: list[str]) -> str:
        fresh = [o for o in options if o not in used_names] or options
        choice = rng.choice(fresh)
        used_names.add(choice)
        return choice

    for plan in plans:
        region = world.regions[plan.id]
        key = plan.kind if plan.kind in ("start", "final") else plan.elements[0]
        region.name = pick(w["region_names"][key])
        region.mood = w["moods"][key]
        people = world.peoples.get(f"volk-{plan.id}") or world.peoples.get("volk-start" if plan.kind == "start" else "")
        if people is not None:
            people.name = pick(people_names)
            people.description = f"Die Bewohner der {region.name}, eigensinnig und stolz auf ihre Heimat."
        element = plan.elements[0] if plan.elements else "stahl"
        for loc in [l for l in world.locations.values() if l.region == plan.id]:
            if loc.type == "siedlung":
                loc.name = f"Dorf {used_settlements.pop()}" if used_settlements else pick(w["settlements"])
                loc.description = (f"Ein paar Dutzend Häuser drängen sich um einen Marktplatz. "
                                   f"{'Aus dem Gasthaus dringt Gelächter.' if loc.inn else 'Hunde bellen, irgendwo hämmert ein Schmied.'}")
            elif loc.type == "schrein":
                loc.name = w["shrine_names"].get(loc.shrine_element or "", "Vorhof des Siegels") if plan.kind != "final" else "Vorhof des Siegels"
                loc.description = "Ein stiller Ort aus altem Stein. Die Luft vibriert vor uralter Kraft."
            elif loc.type == "dungeon":
                loc.name = pick(w["dungeons"])
                loc.description = "Eingestürzte Gänge, feuchte Wände und das Echo tropfenden Wassers. Irgendwo tief drinnen bewegt sich etwas."
            elif loc.type == "hort":
                loc.name = "Thronsaal der Leere" if plan.kind == "final" else f"Hort der {region.name}"
                loc.description = "Ein gewaltiger Saal, in dem jeder Schritt widerhallt. In der Mitte wartet der Herr dieses Ortes."
            else:
                loc.name = pick(w["wild_names"].get(element, w["wild_names"]["stahl"]))
                loc.description = f"{region.mood.split('. ')[0].rstrip('.')}. Ein Pfad windet sich durch das Gelände."
            for n, feature in enumerate(loc.features):
                feature.name = ["Verwitterter Wegstein", "Alter Baumstumpf", "Eingestürzte Mauer", "Rostige Truhe",
                                "Verlassenes Lagerfeuer", "Moosbewachsene Statue"][(n + len(loc.id)) % 6]
                feature.description = "Es lohnt sich vielleicht, genauer hinzusehen." if (feature.hidden_item or feature.hidden_path) else ""
        for npc_id in plan.npcs.values():
            npc = world.npcs[npc_id]
            npc.name = f"{pick(w['first_names'])} {rng.choice(w['last_names'])}"
            npc.appearance = rng.choice(w["appearances"])
            npc.personality = rng.choice(w["personalities"])
            npc.speech = rng.choice(w["speech"])
            npc.wants = "Ruhe und ein gutes Geschäft." if npc.shop else ""
        for slot, loc, n in _creature_slots(world, plan):
            if n >= 0:
                entry = loc.encounter.enemies[n]
                names = w["creatures"][entry.elements[0] if entry.elements else "stahl"]
                entry.name = names[entry.tier]
            else:
                loc.encounter.phases[-n - 1][0].name = f"{rng.choice(w['final_boss'])}, {-n + 1}. Gestalt"
            if loc.encounter:
                loc.encounter.description = loc.encounter.description or "Feindselige Wesen versperren den Weg."
        if plan.kind == "final":
            final_name = rng.choice(w["final_boss"])
            world.locations[plan.roles["thron"]].encounter.enemies[0].name = final_name
            for p, phase in enumerate(world.locations[plan.roles["thron"]].encounter.phases):
                phase[0].name = f"{final_name}, {p + 2}. Gestalt"
        if plan.key_feature:
            _key_spec(world, plan).name = pick(w["key_items"])
        if plan.side_feature:
            _side_spec(world, plan).name = pick(w["quest_items"])


def _key_spec(world: World, plan: RegionPlan) -> ItemSpec:
    loc, feature = plan.key_feature  # type: ignore[misc]
    return next(f for f in world.locations[loc].features if f.id == feature).hidden_item  # type: ignore[return-value]


def _side_spec(world: World, plan: RegionPlan) -> ItemSpec:
    loc, feature = plan.side_feature  # type: ignore[misc]
    return next(f for f in world.locations[loc].features if f.id == feature).hidden_item  # type: ignore[return-value]


def apply_region_naming(world: World, plan: RegionPlan, naming: RegionNaming) -> None:
    """Copies LLM names into the skeleton by id. Unknown ids are ignored; slots
    the LLM left out keep the offline names (``name_offline`` runs first).
    """
    region = world.regions[plan.id]
    region.name, region.mood = naming.name or region.name, naming.mood or region.mood
    people = world.peoples.get(f"volk-{plan.id}") or (world.peoples.get("volk-start") if plan.kind == "start" else None)
    if people is not None:
        people.name = naming.people_name or people.name
        people.description = naming.people_description or people.description
    for named in naming.locations:
        loc = world.locations.get(named.id)
        if loc is None or loc.region != plan.id:
            continue
        loc.name, loc.description = named.name or loc.name, named.description or loc.description
        by_id = {f.id: f for f in loc.features}
        for nf in named.features:
            if nf.id in by_id:
                by_id[nf.id].name = nf.name or by_id[nf.id].name
                by_id[nf.id].description = nf.description or by_id[nf.id].description
    for named in naming.npcs:
        npc = world.npcs.get(named.id)
        if npc is None or npc.id not in plan.npcs.values():
            continue
        npc.name, npc.appearance, npc.personality = named.name, named.appearance, named.personality
        npc.speech, npc.wants = named.speech, named.wants or npc.wants
    slots = {slot: (loc, n) for slot, loc, n in _creature_slots(world, plan)}
    for creature in naming.creatures:
        if creature.id in slots:
            loc, n = slots[creature.id]
            entry = loc.encounter.enemies[n] if n >= 0 else loc.encounter.phases[-n - 1][0]
            entry.name = creature.name or entry.name
            loc.encounter.description = creature.description or loc.encounter.description
    if plan.key_feature and naming.key_item:
        _key_spec(world, plan).name = naming.key_item
    if plan.side_feature and naming.side_item:
        _side_spec(world, plan).name = naming.side_item
    quest_ids = ([plan.main_quest] if plan.main_quest else []) + plan.side_quests
    for quest_id, name in zip(quest_ids, naming.quest_names):
        if name:
            world.quests[quest_id].name = name


def name_with_llm(world: World, plans: list[RegionPlan], llm, theme: str) -> None:
    from .interpret import prompt
    from .llm import ask_model

    system = prompt("worldgen")
    request = {"thema": theme or "klassische High Fantasy",
               "regionen": [{"art": p.kind, "elemente": p.elements} for p in plans],
               "endgegner_phasen": 1 + len(world.locations[world.final_location].encounter.phases)}
    naming = ask_model(llm, system, json.dumps({"aufgabe": "welt", **request}, ensure_ascii=False), WorldNaming)
    world.name, world.premise = naming.name, naming.premise
    for plan in plans:
        payload = {"aufgabe": "region", **region_request(world, plan, theme)}
        region_naming = ask_model(llm, system, json.dumps(payload, ensure_ascii=False, indent=1), RegionNaming,
                                  max_tokens=8000)
        apply_region_naming(world, plan, region_naming)
    thron = world.locations[world.final_location].encounter
    for entry, name in zip([thron.enemies[0]] + [p[0] for p in thron.phases], naming.final_bosses):
        entry.name = name


# --- 3. finalize -------------------------------------------------------------------


def q(name: str) -> str:
    """Names in German quotation marks read correctly in any grammatical case."""
    return f"„{name}“"


def finalize(world: World, plans: list[RegionPlan]) -> None:
    """Writes every text that must match the structure exactly."""
    locs = world.locations
    for plan in plans:
        region = world.regions[plan.id]
        if plan.kind == "start":
            elder = world.npcs[plan.npcs["aelteste"]]
            field_loc = locs[plan.roles["wildnis"]]
            pest = field_loc.encounter.enemies[0].name
            intro = world.quests[plan.main_quest]
            if intro.name == PLACEHOLDER:
                intro.name = f"Ein Hilferuf aus {locs[plan.roles['siedlung']].name}"
            texts = [f"Höre {elder.name} an.", f"Vertreibe die Wesen ({q(pest)}) bei {q(field_loc.name)}.",
                     f"Berichte {elder.name} davon."]
            for step, text in zip(intro.steps, texts):
                step.text = text
            regions = [q(world.regions[p.id].name) for p in plans if p.kind == "element" and p.tier == 0]
            elder.knowledge = [world.premise, f"Bei {q(field_loc.name)} treiben {q(pest)} ihr Unwesen.",
                               "Die Splitter der Elemente werden von den Herren der Regionen bewacht.",
                               f"Die Wege nach {' und '.join(regions)} stehen euch offen."]
            elder.wants = elder.wants or f"Dass jemand die {q(pest)} vertreibt."
            continue
        if plan.kind == "final":
            gate = next(c for c in locs["s-weg"].connections if c.to == plan.roles["vorhof"])
            gate.requirement.text = (f"Ein Tor aus erstarrtem Licht versperrt den Weg nach {q(locs[plan.roles['vorhof']].name)}. "
                                     f"Erst wenn {world.shards_needed} Splitter im Siegel ruhen, öffnet es sich.")
            thron = locs[plan.roles["thron"]]
            if thron.encounter.description in ("", PLACEHOLDER, "Feindselige Wesen versperren den Weg."):
                thron.encounter.description = f"{q(thron.encounter.enemies[0].name)} – das, was unter dem Siegel lauert."
            continue
        key_name = _key_spec(world, plan).name
        side_name = _side_spec(world, plan).name
        hort, verlies, wildnis = locs[plan.roles["hort"]], locs[plan.roles["verlies"]], locs[plan.roles["wildnis"]]
        boss = hort.encounter.enemies[0].name
        key_feature = next(f for f in verlies.features if f.id == plan.key_feature[1])
        side_loc = locs[plan.side_feature[0]]
        side_feature = next(f for f in side_loc.features if f.id == plan.side_feature[1])
        shrine = locs[plan.roles["schrein"]]
        path_feature = next(f for f in wildnis.features if f.hidden_path == shrine.id)

        lock = next(c for c in verlies.connections if c.to == hort.id)
        lock.requirement.item_name = key_name
        lock.requirement.text = f"Der Weg nach {q(hort.name)} ist versperrt. Nur wer {q(key_name)} besitzt, kann ihn öffnen."
        for loc in locs.values():
            for con in loc.connections:
                if con.requirement and con.requirement.kind == "shards" and con.to == plan.roles["eingang"]:
                    con.requirement.text = (f"Eine Barriere aus wirbelnden Elementen versperrt den Weg nach {q(region.name)}. "
                                            f"Erst wenn {con.requirement.count} Splitter im Siegel ruhen, lässt sie euch durch.")

        sage = world.npcs[plan.npcs["kundige"]]
        hunt_target = wildnis.encounter.enemies[0].name
        element = plan.elements[0].capitalize()
        sage.knowledge = [
            f"{q(boss)} haust in {q(hort.name)} und bewacht den Splitter des Elements {element}.",
            f"Der Weg nach {q(hort.name)} öffnet sich nur mit {q(key_name)}.",
            f"{q(key_name)} liegt verborgen in {q(verlies.name)}, dort bei {q(key_feature.name)}.",
            f"Hinter {q(path_feature.name)} bei {q(wildnis.name)} soll ein vergessener Pfad zu {q(shrine.name)} führen.",
            f"Bei {q(wildnis.name)} machen {q(hunt_target)} die Wege unsicher.",
        ]
        petitioner = world.npcs[plan.npcs["bittsteller"]]
        petitioner.knowledge = [f"{q(side_name)} ging bei {q(side_loc.name)} verloren, vielleicht bei {q(side_feature.name)}."]
        petitioner.wants = petitioner.wants or f"{q(side_name)} zurückbekommen."
        trader = world.npcs[plan.npcs["haendler"]]
        trader.knowledge = trader.knowledge or [f"In {q(verlies.name)} hausen gefährliche Wesen.",
                                                f"{sage.name} weiß viel über {q(boss)}."]

        main = world.quests[plan.main_quest]
        if main.name == PLACEHOLDER:
            main.name = f"Der Splitter von {region.name}"
        main.steps[0].text = f"Erfahre bei {sage.name} in {q(locs[plan.roles['siedlung']].name)}, wo {q(boss)} haust."
        main.steps[1].item_name = key_name
        main.steps[1].text = f"Finde {q(key_name)}."
        main.steps[2].text = f"Besiege {q(boss)} in {q(hort.name)}."
        fetch, hunt = (world.quests[qid] for qid in plan.side_quests)
        if fetch.name == PLACEHOLDER:
            fetch.name = f"{side_name} für {petitioner.name}"
        fetch.steps[0].item_name = fetch.steps[1].item_name = side_name
        fetch.steps[0].text = f"Finde {q(side_name)}."
        fetch.steps[1].text = f"Bringe {q(side_name)} zu {petitioner.name}."
        if hunt.name == PLACEHOLDER:
            hunt.name = f"Jagd bei {wildnis.name}"
        hunt.steps[0].text = f"Vertreibe die {q(hunt_target)} bei {q(wildnis.name)}."
        sage.wants = sage.wants or f"Dass jemand die {q(hunt_target)} bei {q(wildnis.name)} vertreibt."
        hort.encounter.loot = ItemSpec(base=_boss_weapon(plan), rarity="selten", element=plan.elements[0])


def _boss_weapon(plan: RegionPlan) -> str:
    return ["schwert", "bogen", "stab", "streitkolben", "rapier", "talisman", "kettenhemd", "dolch"][int(plan.id[1:]) % 8]


# --- 4. checks ----------------------------------------------------------------------


def check_solvable(world: World) -> list[str]:
    """Explores the world like a party that can win every fight and find
    everything hidden. Returns the problems found (empty = winnable).
    """
    reachable = {world.start_location}
    items: set[str] = set()
    shards: set[str] = set()
    changed = True
    while changed:
        changed = False
        for loc_id in list(reachable):
            loc = world.locations[loc_id]
            for feature in loc.features:
                if feature.hidden_item and feature.hidden_item.name and feature.hidden_item.name not in items:
                    items.add(feature.hidden_item.name)
                    changed = True
            enc = loc.encounter
            if enc and enc.shard and enc.shard not in shards:
                shards.add(enc.shard)
                changed = True
            if enc and enc.loot and enc.loot.name and enc.loot.name not in items:
                items.add(enc.loot.name)
                changed = True
            for con in loc.connections:
                if con.to in reachable:
                    continue
                req = con.requirement
                passable = (
                    req is None
                    or (req.kind == "item" and req.item_name in items)
                    or (req.kind == "shards" and len(shards) >= req.count)
                    or req.kind in ("check", "defeated")
                )
                if passable:
                    reachable.add(con.to)
                    changed = True
    problems = []
    unreachable = sorted(set(world.locations) - reachable)
    if unreachable:
        problems.append(f"Nicht erreichbar: {', '.join(unreachable)}")
    if len(shards) < world.shards_needed:
        problems.append(f"Nur {len(shards)} von {world.shards_needed} Splittern erreichbar")
    if world.final_location and world.final_location not in reachable:
        problems.append("Der Endgegner ist nicht erreichbar")
    for loc in world.locations.values():
        if PLACEHOLDER in (loc.name, loc.description):
            problems.append(f"Ort {loc.id} hat keinen Namen")
        if loc.encounter and any(e.name == PLACEHOLDER for e in loc.encounter.enemies):
            problems.append(f"Kreatur in {loc.id} hat keinen Namen")
    for npc in world.npcs.values():
        if PLACEHOLDER in (npc.name, npc.speech):
            problems.append(f"NSC {npc.id} ist unvollständig")
    for quest in world.quests.values():
        if PLACEHOLDER in [quest.name] + [s.text for s in quest.steps]:
            problems.append(f"Auftrag {quest.id} ist unvollständig")
    return problems


def generate_world(catalog: Catalog, length: str, rng: random.Random, llm=None, theme: str = "") -> World:
    world, plans = build_skeleton(catalog, length, rng)
    name_offline(world, plans, rng)
    if llm is not None:
        name_with_llm(world, plans, llm, theme)
    finalize(world, plans)
    world.validate_references()
    problems = check_solvable(world)
    if problems:
        raise ValueError("Die erzeugte Welt ist fehlerhaft: " + "; ".join(problems))
    return world


def save_world(world: World, path: Path) -> None:
    path.write_text(world.model_dump_json(indent=2), encoding="utf-8")
