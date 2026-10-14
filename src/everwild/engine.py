"""Carries out one turn: joins, interpretation, rules, rewards (design §3).

``run_turn`` mutates the game state and returns a ``TurnReport`` with the
facts each narrator call needs and the numbers for the result boxes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .actions import Action
from .catalog import Catalog
from .interpret import Interpreter
from .models import Character, Item
from .rules import character as ch
from .rules import elements as el
from .rules.combat import Tactic, resolve_fight
from .rules.death import die, recover_grave
from .rules.dice import CheckResult, D20Roll, check, roll_dice
from .rules.enemies import Enemy, EnemySpec, build_enemies, encounter_xp, health_words
from .rules.items import (
    ItemError, add_to_bag, display_name, equip, find_in_bag, give, has_room, make_item, price, remove_from_bag,
    sell_price,
)
from .scene import scene
from .state import GameState
from .world import Connection, Encounter, ItemSpec, LiveEnemy, Location, Quest

OUTCOME_LABELS = {
    "kritischer_erfolg": "kritischer Erfolg", "erfolg": "Erfolg", "erfolg_mit_haken": "Erfolg mit Haken",
    "fehlschlag": "Fehlschlag", "kritischer_fehlschlag": "kritischer Fehlschlag",
}
ATTR_SHORT = {"staerke": "STÄ", "geschick": "GES", "verstand": "VER"}
COMBAT_KINDS = {"angreifen", "faehigkeit", "verteidigen", "gegenstand", "fliehen"}


@dataclass
class PlayerReport:
    rolls: list[str] = field(default_factory=list)
    attacks: int = 0
    hits: int = 0
    damage: int = 0
    healed: int = 0
    hp_lost: int = 0
    xp: int = 0
    gold: int = 0
    items: list[str] = field(default_factory=list)
    level_ups: list[str] = field(default_factory=list)


@dataclass
class GroupReport:
    location: str
    players: list[str]
    facts: list[str] = field(default_factory=list)
    talks: list[dict] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    enemies: list[str] = field(default_factory=list)
    per_player: dict[str, PlayerReport] = field(default_factory=dict)
    ooc: list[str] = field(default_factory=list)
    end_locations: set[str] = field(default_factory=set)
    narration: str = ""

    def report(self, player_id: str) -> PlayerReport:
        return self.per_player.setdefault(player_id, PlayerReport())


@dataclass
class TurnReport:
    turn: int
    groups: list[GroupReport] = field(default_factory=list)
    ooc: list[str] = field(default_factory=list)
    announcements: list[str] = field(default_factory=list)
    finished: bool = False


def bump(player: Character, stat: str, amount: int = 1) -> None:
    player.stats[stat] = player.stats.get(stat, 0) + amount


class TurnEngine:
    def __init__(self, catalog: Catalog, state: GameState, rng: random.Random, interpreter: Interpreter):
        self.catalog = catalog
        self.state = state
        self.rng = rng
        self.interpreter = interpreter
        self.world = state.world

    # --- turn ------------------------------------------------------------------

    def run_turn(self, texts: dict[str, str], names: dict[str, str] | None = None) -> TurnReport:
        """``texts``: player id → everything they wrote since the last turn.
        ``names``: display names, used for new players without a name.
        """
        state = self.state
        state.turn += 1
        report = TurnReport(turn=state.turn)
        names = names or {}

        for player in state.players.values():
            ch.tick_cooldowns(player)
            granted = ch.resolve_pending_ability(self.catalog, self.rng, player, state.turn)
            if granted:
                report.ooc.append(f"{player.name} erhält die Fähigkeit {self.catalog.abilities[granted].name} (zufällig gewählt).")

        joined: set[str] = set()
        for author, text in texts.items():
            if author not in state.players:
                if self._join(author, text, names.get(author, f"Wanderer {author}"), report):
                    joined.add(author)

        acting = {pid: text for pid, text in texts.items() if pid in state.players and state.players[pid].status != "left"}
        for player in state.players.values():
            if player.status == "left":
                continue
            if player.id in acting:
                player.idle_streak = 0
                if player.status == "camp":
                    player.status = "active"
                    report.ooc.append(f"{player.name} kehrt aus dem Lager zurück.")
            elif player.status == "active":
                player.idle_streak += 1
                bump(player, "untaetig")
                if player.idle_streak >= self.catalog.rules.camp_after_idle_turns:
                    player.status = "camp"
                    report.ooc.append(f"{player.name} schlägt ein Lager auf und ruht, bis wieder geschrieben wird.")

        self._gather_for_finale(report)

        for location_id, members in self._groups().items():
            group = GroupReport(location=location_id, players=[p.id for p in members])
            texts_here = {p.id: acting[p.id] for p in members if p.id in acting}
            actions = self.interpreter.actions(self.catalog, scene(self.catalog, state, location_id, members), texts_here)
            self._run_group(location_id, members, {a.player_id: a for a in actions}, group, joined)
            self._quests(members, group)
            group.end_locations = {p.location for p in members}
            report.groups.append(group)
        report.finished = state.finished
        return report

    def _gather_for_finale(self, report: TurnReport) -> None:
        """When the gate opens, every active player is called to the final area (§13)."""
        world = self.world
        if world.finale_started or not world.final_rest or len(set(world.seal)) < world.shards_needed:
            return
        world.finale_started = True
        report.announcements.append(
            "Die Splitter im Siegel erstrahlen, und ihr Ruf erreicht jede Heldin und jeden Helden, wo immer sie sind. "
            f"Ein Sog aus Licht trägt alle nach {world.location(world.final_rest).name}.")
        for player in self.state.active_players():
            dummy = GroupReport(location=player.location, players=[player.id])
            self._arrive(player, player.location, world.final_rest, dummy)

    def _groups(self) -> dict[str, list[Character]]:
        groups: dict[str, list[Character]] = {}
        for player in self.state.active_players():
            groups.setdefault(player.location, []).append(player)
        return groups

    # --- joining ---------------------------------------------------------------

    def _join(self, author: str, text: str, fallback_name: str, report: TurnReport) -> bool:
        state, rules = self.state, self.catalog.rules
        reply = self.interpreter.join(self.catalog, text)
        if not reply.is_join:
            return False
        if sum(1 for p in state.players.values() if p.status != "left") >= rules.max_players:
            report.ooc.append("Das Abenteuer ist voll.")
            return False
        class_id = reply.class_id if reply.class_id in self.catalog.classes and self.catalog.classes[reply.class_id].selectable else "wanderer"
        if class_id == "wanderer":
            choices = ", ".join(c.label for c in self.catalog.classes.values() if c.selectable)
            report.ooc.append(f"{reply.name or fallback_name} reist vorerst als Wanderer. Nenne eine Klasse: {choices}.")
        active = state.active_players()
        location = max({p.location for p in active}, key=lambda loc: sum(p.location == loc for p in active)) if active else self.world.start_location
        player = ch.create_character(
            self.catalog, self.rng, id=author, name=reply.name or fallback_name, class_id=class_id,
            element=reply.element or "stahl", background=reply.background or "",
            class_label=reply.class_label, location=location, turn=state.turn,
        )
        rest = location if self.world.location(location).rest_point else self.world.start_location
        player.last_rest_point = rest
        average = state.average_level()
        if average and average > 1:
            ch.set_xp(self.catalog, player, ch.level_start_xp(self.catalog, max(1, round(average) - 1), state.length), state.length)
            player.hp = ch.max_hp(self.catalog, player)
        state.players[author] = player
        report.ooc.append(f"{player.name} tritt dem Abenteuer bei ({player.class_label}, {self.catalog.rules.elements[player.element].label}).")
        return True

    # --- groups ----------------------------------------------------------------

    def _run_group(self, location_id: str, members: list[Character], actions: dict[str, Action],
                   group: GroupReport, joined: set[str]) -> None:
        for member in members:
            action = actions.get(member.id)
            if action is not None and member.id in joined and action.kind == "nichts":
                del actions[member.id]  # the join message itself, no action in it
                action = None
            if action is None:
                if member.id not in joined:
                    group.facts.append(f"{member.name} ist heute untätig.")
                else:
                    group.facts.append(f"{member.name} stößt neu zur Geschichte ({member.class_label})."
                                       + (f" {member.background.rstrip('.')}." if member.background else ""))
                continue
            self._meta(member, action, group)
            for item_id in action.equip:
                try:
                    equip(self.catalog, member, item_id)
                    group.facts.append(f"{member.name} legt {find_name(member, item_id)} an.")
                except ItemError as error:
                    group.ooc.append(str(error))

        acting = [m for m in members if m.id in actions and m.status == "active"]
        enc = self.world.location(location_id).encounter
        if enc is not None and enc.state == "feindlich":
            live = bool(enc.live)
            seen_before = enc.seen_turn is not None and enc.seen_turn < self.state.turn
            wants_fight = any(actions[m.id].kind == "angreifen" or self._is_combat_ability(actions[m.id]) for m in acting)
            if live or wants_fight or seen_before:
                leavers = set() if (live or wants_fight) else self._slip_away(location_id, acting, actions, group)
                staying = [m for m in acting if m.id not in leavers]
                if staying or live or wants_fight:
                    if self._talk_down(location_id, staying, actions, group):
                        acting = [m for m in acting if actions[m.id].kind != "sprechen"]
                    else:
                        self._fight(location_id, [m for m in members if m.id not in leavers], actions, group)
                        acting = [m for m in acting if m.id in leavers]
                        if not acting:
                            return
            elif enc.seen_turn is None:
                enc.seen_turn = self.state.turn

        movers: dict[str, list[Character]] = {}
        followers: list[tuple[Character, Action]] = []
        for member in acting:
            action = actions[member.id]
            if action.kind == "folgen":
                followers.append((member, action))
                continue
            destination = self._act(location_id, member, action, group, members)
            if destination:
                movers.setdefault(destination, []).append(member)
        for member, action in followers:
            leader = self.state.players.get(action.target or "")
            if leader is None or leader.location == location_id or leader.id == member.id:
                group.facts.append(f"{member.name} will folgen, aber niemand bricht auf.")
                continue
            self._arrive(member, location_id, leader.location, group)
            movers.setdefault(leader.location, []).append(member)
            group.facts.append(f"{member.name} folgt {leader.name}.")

        # idle members follow the group if everyone who acted went the same way
        destinations = {m.location for m in acting}
        if len(destinations) == 1 and location_id not in destinations:
            (dest,) = destinations
            for member in members:
                if member.id not in actions and member.location == location_id:
                    self._arrive(member, location_id, dest, group)
                    movers.setdefault(dest, []).append(member)
                    group.facts.append(f"{member.name} trottet der Gruppe hinterher.")

        for destination, arrivals in movers.items():
            self._on_arrival(destination, arrivals, actions, group)

    # --- meta ------------------------------------------------------------------

    def _meta(self, player: Character, action: Action, group: GroupReport) -> None:
        state = self.state
        if action.leave:
            player.status = "left"
            group.facts.append(f"{player.name} nimmt Abschied von den Gefährten und verlässt das Abenteuer.")
            return
        if action.new_class or action.new_element:
            try:
                new = ch.change_class(self.catalog, self.rng, player, action.new_class or player.class_id,
                                      element=action.new_element, turn=state.turn, length=state.length)
                for name in Character.model_fields:
                    setattr(player, name, getattr(new, name))
                group.ooc.append(f"{player.name} ist jetzt {player.class_label} ({self.catalog.rules.elements[player.element].label}).")
            except ch.CharacterError as error:
                group.ooc.append(f"{player.name}: {error}")
        if action.ability_choice:
            try:
                ch.choose_second_ability(self.catalog, player, action.ability_choice)
                group.ooc.append(f"{player.name} wählt {self.catalog.abilities[action.ability_choice].name}.")
            except ch.CharacterError as error:
                group.ooc.append(f"{player.name}: {error}")
        if action.attribute_choice:
            player.attribute_choice = action.attribute_choice

    # --- single actions outside fights ----------------------------------------

    def _is_combat_ability(self, action: Action) -> bool:
        return (action.kind == "faehigkeit" and action.ability in self.catalog.abilities
                and self.catalog.abilities[action.ability].combat
                and action.ability not in ("heilung", "gruppenheilung", "schattenschritt"))

    def _act(self, location_id: str, player: Character, action: Action, group: GroupReport,
             members: list[Character]) -> str | None:
        """Carries out one action. Returns the destination if the player moved."""
        kind = action.kind
        name = player.name
        if kind == "faehigkeit":
            return self._ability(location_id, player, action, group, members)
        if kind == "bewegen":
            return self._move(location_id, player, action.target, group, members)
        if kind == "untersuchen":
            self._search(location_id, player, action, group)
        elif kind == "sprechen":
            self._talk(location_id, player, action, group, auto=False)
        elif kind == "rasten":
            self._rest(location_id, player, group, members)
        elif kind == "gegenstand":
            self._use_item(player, action, group)
        elif kind == "geben":
            receiver = self.state.players.get(action.target or "")
            try:
                if receiver is None:
                    raise ItemError("Niemand da, dem man etwas geben könnte.")
                item = give(self.catalog, player, receiver, action.item or "")
                bump(player, "verschenkt")
                group.facts.append(f"{name} gibt {receiver.name} {item.name}.")
                group.report(receiver.id).items.append(display_name(self.catalog, item))
            except ItemError as error:
                group.facts.append(f"{name} will etwas weitergeben, aber es klappt nicht: {error}")
        elif kind == "kaufen":
            self._buy(location_id, player, action, group)
        elif kind == "verkaufen":
            self._sell(location_id, player, action, group)
        elif kind == "aufheben":
            self._pick_up(location_id, player, action, group)
        elif kind == "grab_bergen":
            gold, items = recover_grave(self.catalog, player)
            if gold or items:
                group.facts.append(f"{name} birgt die eigenen Habseligkeiten aus dem Grab.")
                group.report(player.id).gold += gold
                group.report(player.id).items += [display_name(self.catalog, i) for i in items]
            else:
                group.facts.append(f"{name} sucht nach dem eigenen Grab, doch hier ist keines.")
        elif kind == "probe":
            result = self._check(player, action.attribute or "geschick", action.difficulty or "mittel", group)
            group.facts.append(f"{name} versucht: {action.summary or 'etwas Gewagtes'} – {OUTCOME_LABELS[result.outcome]}.")
        elif kind == "angreifen" and action.target in self.world.location(location_id).npcs:
            self._attack_npc(location_id, player, action.target, group)
        elif kind in ("angreifen", "verteidigen", "fliehen"):
            group.facts.append(f"{name} ist kampfbereit, doch hier gibt es keinen Gegner.")
        else:
            group.facts.append(f"{name} zögert{': ' + action.summary if action.summary else ''}.")
        return None

    def _check(self, player: Character, attribute: str, difficulty: str, group: GroupReport,
               advantage: str = "normal", auto: bool = False) -> CheckResult:
        rules = self.catalog.rules
        target = rules.difficulties.get(difficulty, rules.difficulties["mittel"])
        modifier = ch.attribute(self.catalog, player, attribute)  # type: ignore[arg-type]
        if auto:
            result = CheckResult(roll=D20Roll((20,), 20, "normal"), modifier=modifier, target=target, outcome="erfolg")
            group.report(player.id).rolls.append(f"{ATTR_SHORT[attribute]}-Probe: sicherer Erfolg")
            return result
        result = check(self.rng, modifier, target, advantage, rules.complication_margin)  # type: ignore[arg-type]
        group.report(player.id).rolls.append(
            f"{ATTR_SHORT[attribute]}-Probe: {result.roll.kept} + {modifier} = {result.total} gegen {target} → {OUTCOME_LABELS[result.outcome]}")
        if result.outcome in ("erfolg", "kritischer_erfolg") and difficulty in rules.xp.check:
            self._xp(player, rules.xp.check[difficulty], group)
        return result

    # movement

    def _connection(self, location_id: str, target: str | None) -> Connection | None:
        return next((c for c in self.world.visible_connections(location_id) if c.to == target), None)

    def _requirement_met(self, location_id: str, player: Character, con: Connection, group: GroupReport,
                         members: list[Character]) -> bool:
        req = con.requirement
        if req is None or con.opened:
            return True
        companions = members  # the group that set out together, even if some already went ahead
        if req.kind == "item":
            return any(
                (i.base == req.item_base and (req.item_name is None or i.name == req.item_name))
                for m in companions for i in ch.all_items(m)
            )
        if req.kind == "affinity":
            return el.effective_affinity(self.catalog, player, req.element or "stahl") >= req.level
        if req.kind == "class":
            return any(m.class_id == req.class_id for m in companions)
        if req.kind == "defeated":
            enc = self.world.location(req.location or location_id).encounter
            return enc is None or enc.state != "feindlich"
        if req.kind == "shards":
            return len(set(self.world.seal)) >= req.count
        if req.kind == "check":
            result = self._check(player, req.attribute or "staerke", req.difficulty or "mittel", group)
            if result.succeeded:
                con.opened = True
            return result.succeeded
        return False

    def _move(self, location_id: str, player: Character, target: str | None, group: GroupReport,
              members: list[Character]) -> str | None:
        con = self._connection(location_id, target)
        if con is None:
            group.facts.append(f"{player.name} sucht einen Weg, findet aber keinen in diese Richtung.")
            return None
        if not self._requirement_met(location_id, player, con, group, members):
            group.facts.append(f"{player.name} kommt nicht weiter: {con.requirement.text}")
            return None
        group.facts.append(f"{player.name} geht nach {self.world.location(con.to).name}.")
        self._arrive(player, location_id, con.to, group)
        return con.to

    def _arrive(self, player: Character, origin: str, destination: str, group: GroupReport) -> None:
        loc = self.world.location(destination)
        player.previous_location = origin
        player.location = destination
        if loc.rest_point:
            player.last_rest_point = destination
        if not loc.discovered:
            loc.discovered = True
            bump(player, "orte_entdeckt")
            group.facts.append(f"{player.name} entdeckt {loc.name}.")
            self._xp(player, self.catalog.rules.xp.new_location, group)
            for quest in self.world.quests.values():
                if quest.kind == "haupt" and quest.region == loc.region:
                    quest.known = True

    def _on_arrival(self, destination: str, arrivals: list[Character], actions: dict[str, Action],
                    group: GroupReport) -> None:
        enc = self.world.location(destination).encounter
        if enc is None or enc.state != "feindlich":
            return
        sneaking = any(actions.get(p.id) and actions[p.id].ability == "spurlos" for p in arrivals)
        if sneaking:
            group.facts.append(f"Die Gruppe schleicht unbemerkt an der Gefahr in {self.world.location(destination).name} vorbei.")
            return
        if enc.ambush and not enc.live:
            group.facts.append(f"Kaum angekommen, wird {', '.join(p.name for p in arrivals)} aus dem Hinterhalt angegriffen!")
            ambushed = {p.id: Action(player_id=p.id, kind="angreifen") for p in arrivals}
            self._fight(destination, arrivals, ambushed, group)
        else:
            enc.seen_turn = self.state.turn
            group.facts.append(f"In {self.world.location(destination).name} lauert Gefahr: "
                               f"{(enc.description or 'feindselige Wesen').rstrip('.')}.")

    # exploring

    def _search(self, location_id: str, player: Character, action: Action, group: GroupReport) -> None:
        loc = self.world.location(location_id)
        features = [f for f in loc.features if f.id == action.target]
        if not features:
            features = [f for f in loc.features if (f.hidden_item or f.hidden_path) and not f.searched]
            features.sort(key=lambda f: self.catalog.rules.difficulties.get(f.search_difficulty, 12))
        if not features:
            group.facts.append(f"{player.name} sieht sich gründlich um, findet aber nichts Verborgenes.")
            return
        feature = features[0]
        if feature.searched or not (feature.hidden_item or feature.hidden_path):
            group.facts.append(f"{player.name} untersucht {feature.name}, findet aber nichts Neues.")
            return
        attribute = action.attribute or ("geschick" if feature.hidden_path else "verstand")
        advantage = "vorteil" if player.class_id == "waldlaeufer" else "normal"
        result = self._check(player, attribute, feature.search_difficulty, group, advantage)
        if not result.succeeded:
            group.facts.append(f"{player.name} untersucht {feature.name}, doch was immer dort verborgen ist, bleibt verborgen.")
            return
        feature.searched = True
        if feature.hidden_item:
            item = self._make(feature.hidden_item)
            self._give_item(player, item, location_id, group)
            group.facts.append(f"{player.name} findet bei {feature.name}: {item.name}.")
        if feature.hidden_path:
            con = next(c for c in loc.connections if c.to == feature.hidden_path)
            con.found = True
            group.facts.append(f"{player.name} entdeckt bei {feature.name} einen verborgenen Weg nach {self.world.location(con.to).name}.")

    def _make(self, spec: ItemSpec) -> Item:
        return make_item(self.catalog, self.rng, spec.base, rarity=spec.rarity, element=spec.element,
                         name=spec.name, quantity=spec.quantity, special=spec.special)

    def _give_item(self, player: Character, item: Item, location_id: str, group: GroupReport) -> bool:
        try:
            add_to_bag(self.catalog, player, item)
            group.report(player.id).items.append(display_name(self.catalog, item))
            return True
        except ItemError:
            self.world.location(location_id).items.append(item)
            group.facts.append(f"{item.name} bleibt liegen – der Rucksack von {player.name} ist voll.")
            return False

    def _pick_up(self, location_id: str, player: Character, action: Action, group: GroupReport) -> None:
        loc = self.world.location(location_id)
        item = next((i for i in loc.items if i.id == action.item), None)
        if item is None:
            group.facts.append(f"{player.name} sucht nach etwas zum Aufheben, aber hier liegt nichts dergleichen.")
            return
        if not has_room(self.catalog, player, item):
            group.facts.append(f"{player.name} kann {item.name} nicht mehr tragen.")
            return
        loc.items.remove(item)
        add_to_bag(self.catalog, player, item)
        group.report(player.id).items.append(display_name(self.catalog, item))
        group.facts.append(f"{player.name} hebt {item.name} auf.")

    # people

    def _npc_here(self, location_id: str, npc_id: str | None):
        npcs = self.world.npcs_at(location_id)
        return next((n for n in npcs if n.id == npc_id), None)

    def _talk(self, location_id: str, player: Character, action: Action, group: GroupReport, auto: bool) -> None:
        npc = self._npc_here(location_id, action.target)
        if npc is None:
            group.facts.append(f"{player.name} spricht ins Leere: „{action.speech or '…'}“ – niemand antwortet.")
            return
        if npc.attitude <= -2:
            group.facts.append(f"{player.name} spricht {npc.name} an, doch {npc.name} ist feindselig und verweigert jedes Wort.")
            return
        persuaded = None
        if auto or action.difficulty:
            result = self._check(player, "verstand", action.difficulty or "mittel", group, auto=auto)
            persuaded = result.succeeded
            if result.succeeded and npc.attitude < 2:
                npc.attitude += 1
            elif result.outcome == "kritischer_fehlschlag" and npc.attitude > -2:
                npc.attitude -= 1
        group.talks.append({"npc": npc.id, "spieler": player.name, "sagt": action.speech or action.summary,
                            "ueberzeugt": persuaded})
        group.facts.append(f"{player.name} spricht mit {npc.name}" + (
            "" if persuaded is None else (" und überzeugt" if persuaded else ", kann aber nicht überzeugen")) + ".")

    def _attack_npc(self, location_id: str, player: Character, npc_id: str, group: GroupReport) -> None:
        npc = self.world.npcs[npc_id]
        result = self._check(player, "staerke", "mittel", group)
        if npc.people and npc.people in self.world.peoples:
            self.world.peoples[npc.people].attitude = max(-2, self.world.peoples[npc.people].attitude - 1)
        for other in self.world.npcs.values():
            if other.people == npc.people and other.attitude > -2:
                other.attitude -= 1
        if not result.succeeded:
            group.facts.append(f"{player.name} greift {npc.name} an, doch {npc.name} entkommt. Das wird sich herumsprechen.")
            return
        if npc.indispensable:
            group.facts.append(f"{player.name} schlägt {npc.name} nieder. {npc.name} bleibt bewusstlos liegen. Das wird sich herumsprechen.")
            return
        npc.alive = False
        group.facts.append(f"{player.name} tötet {npc.name}. Das wird Folgen haben.")

    def _buy(self, location_id: str, player: Character, action: Action, group: GroupReport) -> None:
        npc = self._npc_here(location_id, action.target)
        if npc is None or action.item not in npc.shop:
            group.facts.append(f"{player.name} möchte etwas kaufen, aber das gibt es hier nicht.")
            return
        item = make_item(self.catalog, self.rng, action.item, name=self.catalog.items[action.item].name)
        cost = price(self.catalog, item)
        if npc.attitude >= 1:
            cost = max(1, int(cost * 0.9))
        if player.gold < cost:
            group.facts.append(f"{player.name} möchte {item.name} kaufen, hat aber nicht genug Gold.")
            return
        if not has_room(self.catalog, player, item):
            group.facts.append(f"{player.name} möchte {item.name} kaufen, aber der Rucksack ist voll.")
            return
        player.gold -= cost
        add_to_bag(self.catalog, player, item)
        report = group.report(player.id)
        report.gold -= cost
        report.items.append(display_name(self.catalog, item))
        group.facts.append(f"{player.name} kauft bei {npc.name} {item.name}.")

    def _sell(self, location_id: str, player: Character, action: Action, group: GroupReport) -> None:
        npc = self._npc_here(location_id, action.target)
        try:
            if npc is None or not npc.shop:
                raise ItemError("Hier ist kein Händler.")
            item = find_in_bag(player, action.item or "")
            value = sell_price(self.catalog, item)
            if value <= 0:
                raise ItemError(f"{item.name} will niemand kaufen.")
            remove_from_bag(player, item.id, 1)
            player.gold += value
            group.report(player.id).gold += value
            group.facts.append(f"{player.name} verkauft {item.name} an {npc.name}.")
        except ItemError as error:
            group.facts.append(f"{player.name} will etwas verkaufen, aber: {error}")

    # rest and items

    def _rest(self, location_id: str, player: Character, group: GroupReport, members: list[Character]) -> None:
        loc = self.world.location(location_id)
        full = ch.max_hp(self.catalog, player)
        amount = full if (loc.rest_point or loc.inn) else int(full * self.catalog.rules.rest_heal_fraction)
        cleric = next((m for m in members if m.class_id == "kleriker" and m.location == location_id), None)
        if cleric is not None:
            amount += ch.attribute(self.catalog, cleric, "verstand")
        healed = ch.heal(self.catalog, player, amount)
        group.report(player.id).healed += healed
        if loc.rest_point:
            player.last_rest_point = location_id
        group.facts.append(f"{player.name} rastet" + (" und erholt sich vollständig." if player.hp == full else "."))
        if loc.shrine_element and location_id not in player.shrines_used:
            if el.gain_affinity(self.catalog, player, loc.shrine_element):
                player.shrines_used.append(location_id)
                label = self.catalog.rules.elements[loc.shrine_element].label
                group.facts.append(f"Am Schrein spürt {player.name} die Kraft des Elements {label} – die Verbindung wächst.")
                group.report(player.id).level_ups.append(f"Affinität {label} {player.affinity[loc.shrine_element]}")

    def _use_item(self, player: Character, action: Action, group: GroupReport) -> None:
        try:
            item = find_in_bag(player, action.item or "")
        except ItemError:
            group.facts.append(f"{player.name} kramt im Rucksack, findet aber nicht, was gesucht wird.")
            return
        effect = self.catalog.items[item.base].effect
        if effect != "heal_half":
            group.facts.append(f"{player.name} betrachtet {item.name} – das entfaltet seine Wirkung erst im Kampf.")
            return
        target = self.state.players.get(action.target or "") or player
        if target.location != player.location:
            target = player
        healed = ch.heal(self.catalog, target, int(ch.max_hp(self.catalog, target) * self.catalog.rules.potion_heal_fraction))
        remove_from_bag(player, item.id, 1)
        group.report(target.id).healed += healed
        group.facts.append(f"{player.name} " + ("trinkt" if target is player else f"gibt {target.name}") + f" {item.name}.")

    # abilities outside fights

    def _ability(self, location_id: str, player: Character, action: Action, group: GroupReport,
                 members: list[Character]) -> str | None:
        ability = action.ability or ""
        name = player.name
        info = self.catalog.abilities.get(ability)
        if info is None or ability not in player.abilities:
            group.facts.append(f"{name} versucht eine Fähigkeit, die {name} nicht beherrscht.")
            return None
        if not ch.ability_ready(player, ability):
            group.facts.append(f"{name} will {info.name} einsetzen, doch die Kraft dafür ist noch nicht zurück.")
            return None
        used = True
        destination = None
        if ability == "betoeren":
            self._talk(location_id, player, action, group, auto=True)
        elif ability == "schattenschritt":
            self._check(player, "geschick", action.difficulty or "schwer", group, auto=True)
            group.facts.append(f"{name} bewegt sich lautlos wie ein Schatten: {action.summary or 'es gelingt'}.")
        elif ability in ("heilung", "gruppenheilung"):
            targets = [m for m in members if m.location == location_id] if ability == "gruppenheilung" else \
                [self.state.players.get(action.target or "") or player]
            for target in targets:
                amount = (ch.max_hp(self.catalog, target) // 2 if ability == "gruppenheilung"
                          else sum(roll_dice(self.rng, "2d6")) + ch.attribute(self.catalog, player, "verstand"))
                group.report(target.id).healed += ch.heal(self.catalog, target, amount)
            group.facts.append(f"{name} wirkt {info.name}.")
        elif ability == "erkenntnis":
            group.questions.append(action.speech or action.summary)
            group.facts.append(f"{name} versenkt sich in arkane Schau und fragt: „{action.speech or action.summary}“")
        elif ability in ("spurlos", "abkuerzung", "teleport"):
            destination = self._ability_move(location_id, player, ability, action.target, group, members)
            used = destination is not None
        elif ability == "meisterdieb":
            npc = self._npc_here(location_id, action.target)
            if npc is None or not npc.shop:
                group.facts.append(f"{name} sucht ein Opfer für einen Diebstahl, doch hier gibt es nichts zu holen.")
                used = False
            else:
                item = make_item(self.catalog, self.rng, self.rng.choice(npc.shop))
                self._give_item(player, item, location_id, group)
                npc.memory.append(f"Vermisst seit Tag {self.state.turn}: {item.name}")
                group.facts.append(f"{name} stiehlt {npc.name} unbemerkt {item.name}.")
        elif ability == "freund_der_voelker":
            npc = self._npc_here(location_id, action.target)
            people = self.world.peoples.get(npc.people) if npc and npc.people else self.world.peoples.get(action.target or "")
            if people is None:
                group.facts.append(f"{name} findet hier niemanden, dessen Volk zu gewinnen wäre.")
                used = False
            else:
                people.attitude = min(2, people.attitude + 1)
                for other in self.world.npcs.values():
                    if other.people == people.id:
                        other.attitude = min(2, other.attitude + 1)
                group.facts.append(f"{name} gewinnt die Herzen des Volkes {people.name}.")
        else:
            group.facts.append(f"{name} hebt zu {info.name} an, doch ohne Gegner verpufft die Kraft ungenutzt.")
            used = False
        if used:
            ch.use_ability(self.catalog, player, ability)
        return destination

    def _ability_move(self, location_id: str, player: Character, ability: str, target: str | None,
                      group: GroupReport, members: list[Character]) -> str | None:
        if ability == "teleport":
            known = {loc.id for loc in self.world.locations.values() if loc.rest_point and loc.discovered}
            if target not in known:
                group.facts.append(f"{player.name} kennt keinen solchen Rastplatz als Ziel.")
                return None
            for member in [m for m in members if m.location == location_id]:
                self._arrive(member, location_id, target, group)
            group.facts.append(f"{player.name} öffnet ein flirrendes Tor – die Gruppe tritt hindurch nach {self.world.location(target).name}.")
            return target
        if ability == "abkuerzung":
            for first in self.world.visible_connections(location_id):
                second = self._connection(first.to, target)
                if second and not first.requirement and not second.requirement:
                    self._arrive(player, location_id, first.to, group)
                    self._arrive(player, first.to, target, group)
                    group.facts.append(f"{player.name} kennt eine Abkürzung und erreicht {self.world.location(target).name} an einem Tag.")
                    return target
            return self._move(location_id, player, target, group, members)
        # spurlos: a normal move that slips past any danger at the destination
        return self._move(location_id, player, target, group, members)

    # --- fights ----------------------------------------------------------------

    def _slip_away(self, location_id: str, acting: list[Character], actions: dict[str, Action],
                   group: GroupReport) -> set[str]:
        """After a threat was seen: going back is free, moving on needs a GES check (§11)."""
        leavers: set[str] = set()
        leaders = {m.id: m for m in acting}
        for member in acting:
            action = actions[member.id]
            target = action.target
            if action.kind == "folgen" and target in leaders:
                target = actions[target].target if actions[target].kind == "bewegen" else None
            elif action.kind == "faehigkeit" and action.ability in ("spurlos", "teleport"):
                leavers.add(member.id)
                continue
            elif action.kind != "bewegen":
                continue
            if target is None:
                continue
            if target == member.previous_location:
                leavers.add(member.id)
                continue
            result = self._check(member, "geschick", "mittel", group)
            if result.succeeded:
                leavers.add(member.id)
                group.facts.append(f"{member.name} schleicht sich unbemerkt an den Wesen vorbei.")
            else:
                group.facts.append(f"{member.name} versucht vorbeizuschleichen, wird aber bemerkt.")
        return leavers

    def _talk_down(self, location_id: str, members: list[Character], actions: dict[str, Action],
                   group: GroupReport) -> bool:
        """Before a fight: if the group only talks, one VER check (schwer) can avoid it."""
        enc = self.world.location(location_id).encounter
        speakers = [m for m in members if m.id in actions and actions[m.id].kind == "sprechen"]
        others = [m for m in members if m.id in actions and actions[m.id].kind not in ("sprechen", "nichts")]
        if enc is None or enc.live or not speakers or others:
            return False
        speaker = speakers[0]
        result = self._check(speaker, "verstand", "schwer", group)
        if result.succeeded:
            enc.state = "friedlich"
            group.facts.append(f"{speaker.name} redet auf die Wesen ein – und tatsächlich: Sie lassen die Gruppe in Ruhe.")
            return True
        group.facts.append(f"{speaker.name} versucht zu verhandeln, doch die Wesen greifen an.")
        return False

    def _enemies_for(self, location: Location, players: int) -> list[Enemy]:
        enc = location.encounter
        assert enc is not None
        if enc.live:
            return [Enemy(**e.model_dump()) for e in enc.live]
        specs = [EnemySpec(e.name, e.tier, tuple(e.elements), e.count) for e in enc.enemies]
        return build_enemies(self.catalog, specs, self.world.region_of(location.id).level, players)

    def _tactic(self, action: Action | None) -> Tactic:
        if action is None:
            return Tactic("untaetig")
        kind = action.kind
        if kind == "angreifen":
            return Tactic("angriff", target=action.target)
        if kind == "faehigkeit":
            return Tactic("faehigkeit", ability=action.ability, target=action.target)
        if kind == "verteidigen":
            return Tactic("verteidigen", target=action.target)
        if kind == "gegenstand":
            return Tactic("gegenstand", item_id=action.item, target=action.target)
        if kind in ("fliehen", "bewegen", "folgen"):
            return Tactic("fliehen")
        return Tactic("verteidigen")

    def _fight(self, location_id: str, fighters: list[Character], actions: dict[str, Action], group: GroupReport) -> None:
        loc = self.world.location(location_id)
        enc = loc.encounter
        assert enc is not None
        fighters = [f for f in fighters if f.location == location_id and f.status == "active"]
        enemies = self._enemies_for(loc, len(fighters))
        tactics = {f.id: self._tactic(actions.get(f.id)) for f in fighters}
        for fighter in fighters:
            action = actions.get(fighter.id)
            if action is not None and action.kind not in COMBAT_KINDS | {"bewegen", "folgen", "nichts"}:
                group.facts.append(f"{fighter.name} will {action.summary or 'etwas anderes tun'}, "
                                   "doch mitten im Kampf bleibt dafür keine Zeit – stattdessen deckt sich die Figur.")
        hp_before = {f.id: f.hp for f in fighters}
        result = resolve_fight(self.catalog, self.rng, fighters, tactics, enemies)
        self._summarize_fight(result, fighters, enemies, group, hp_before)

        for pid in result.escaped:
            player = self.state.players[pid]
            back = player.previous_location or self.world.start_location
            if back != location_id:
                player.previous_location, player.location = location_id, back
            group.facts.append(f"{player.name} entkommt nach {self.world.location(player.location).name}.")

        if result.outcome == "gewonnen":
            enc.state = "besiegt"
            enc.live = []
            self._victory(location_id, enc, [self.state.players[p] for p in result.participants], group)
        elif result.outcome in ("offen", "entkommen"):
            enc.live = [LiveEnemy(**vars(e)) for e in enemies if e.alive]
            if result.outcome == "offen":
                group.facts.append("Der Kampf ist noch nicht entschieden.")
        else:
            enc.live = []  # the enemies recover fully after a lost fight (§10)
            for pid in result.died:
                player = self.state.players[pid]
                outcome = die(self.catalog, self.rng, player, turn=self.state.turn, length=self.state.length)
                bump(player, "tode")
                group.facts.append(f"{player.name} fällt. Später erwacht {player.name} am Rastplatz "
                                   f"{self.world.location(player.location).name} – doch ein Teil der Habe bleibt im Grab zurück.")
                group.report(pid).level_ups.append(
                    f"🪦 Gestorben: {outcome.grave.gold} Gold und {len(outcome.grave.items)} Gegenstände im Grab, −{outcome.xp_lost} EP")
        group.enemies = [f"{e.name} ({health_words(e)})" for e in enemies]

    def _summarize_fight(self, result, fighters, enemies, group: GroupReport, hp_before: dict[str, int]) -> None:
        names = {f.id: f.name for f in fighters} | {e.id: e.name for e in enemies}
        for event in result.events:
            if event.actor in names and event.kind == "angriff" and event.actor in hp_before:
                rep = group.report(event.actor)
                rep.attacks += 1
                rep.hits += bool(event.hit)
                rep.damage += event.damage
            elif event.kind == "heilung":
                group.report(event.target).healed += event.healed
        for fighter in fighters:
            rep = group.report(fighter.id)
            rep.hp_lost += max(0, hp_before[fighter.id] - fighter.hp)
        lines = []
        for fighter in fighters:
            rep = group.report(fighter.id)
            what = f"{fighter.name}: {rep.hits} von {rep.attacks} Angriffen treffen" if rep.attacks else f"{fighter.name} hält sich zurück"
            lines.append(what)
        defeated = [e.name for e in enemies if e.hp <= 0]
        fled = [e.name for e in enemies if e.fled]
        downed = [names[e.actor] for e in result.events if e.kind == "kampfunfaehig"]
        notes = [e for e in result.events if e.kind == "faehigkeit" or e.note in ("wuchtschlag", "feuerball", "schattenschritt", "gezielter_schuss")]
        ability_names = sorted({self.catalog.abilities[n.note.split(':')[0]].name for n in notes if n.note.split(':')[0] in self.catalog.abilities})
        group.facts.append(
            "Kampf: " + "; ".join(lines)
            + (f". Eingesetzte Fähigkeiten: {', '.join(ability_names)}" if ability_names else "")
            + (f". Besiegt: {', '.join(defeated)}" if defeated else "")
            + (f". Geflohen: {', '.join(fled)}" if fled else "")
            + (f". Zu Boden gegangen: {', '.join(downed)}" if downed else "")
            + "."
        )
        if result.outcome == "gewonnen":
            group.facts.append("Die Gruppe siegt.")
        elif result.outcome == "verloren":
            group.facts.append("Die Gruppe unterliegt.")
        elif result.outcome == "entkommen":
            group.facts.append("Die Gruppe entkommt dem Kampf.")

    def _victory(self, location_id: str, enc: Encounter, winners: list[Character], group: GroupReport) -> None:
        if not winners:
            return
        specs = [EnemySpec(e.name, e.tier, tuple(e.elements), e.count) for e in enc.enemies]
        xp = encounter_xp(self.catalog, specs)
        for player in winners:
            self._xp(player, xp, group)
            bump(player, "gegner_besiegt", sum(e.count for e in enc.enemies))
        if enc.phase < len(enc.phases):
            enc.phase += 1
            enc.enemies = enc.phases[enc.phase - 1]
            enc.state = "feindlich"
            enc.seen_turn = self.state.turn - 1  # the next phase attacks right away next turn
            group.facts.append(f"Doch der Kampf ist nicht vorbei: {', '.join(e.name for e in enc.enemies)} erhebt sich!")
            return
        if enc.shard and enc.shard not in self.world.seal:
            self.world.seal.append(enc.shard)
            label = self.catalog.rules.elements[enc.shard].label
            group.facts.append(f"Der Splitter des Elements {label} löst sich aus der Asche und fliegt davon, zum Siegel. "
                               f"({len(set(self.world.seal))} von {self.world.shards_needed} Splittern ruhen nun im Siegel.)")
        if location_id == self.world.final_location:
            self.state.finished = True
            group.facts.append("Die letzte Finsternis weicht. Das Siegel ist erneuert – das Abenteuer ist vollbracht.")
        loot = self.catalog.loot
        region = self.world.region_of(location_id)
        gold = 0
        items: list[Item] = []
        for spec in specs:
            tier = loot.tiers[spec.tier]
            for _ in range(spec.count):
                gold += sum(roll_dice(self.rng, tier.gold))
                if self.rng.random() < tier.item_chance:
                    base = self.rng.choice(loot.item_pool)
                    rarity = "selten" if self.rng.random() < tier.rare_chance and base not in ("heiltrank",) else "gewoehnlich"
                    element = "stahl"
                    elements = [e for e in region.elements if e != "stahl"]
                    if elements and self.rng.random() < loot.region_element_chance and self.catalog.items[base].category in ("waffe", "ruestung", "talisman", "schild", "verbrauchsgut"):
                        element = self.rng.choice(elements)
                    if base in ("schriftrolle", "elementoel") and element == "stahl":
                        element = self.rng.choice(elements or ["feuer", "wasser", "erde", "luft", "licht", "schatten"])
                    items.append(make_item(self.catalog, self.rng, base, rarity=rarity, element=element))
        if enc.loot:
            items.append(self._make(enc.loot))
        share, rest = divmod(gold, len(winners))
        for n, player in enumerate(winners):
            amount = share + (1 if n < rest else 0)
            player.gold += amount
            bump(player, "gold_erbeutet", amount)
            group.report(player.id).gold += amount
        for item in items:
            receiver = self.rng.choice(winners)
            self._give_item(receiver, item, location_id, group)
            group.facts.append(f"Beute: {receiver.name} erhält {item.name}.")

    # --- quests ------------------------------------------------------------------

    def _quests(self, members: list[Character], group: GroupReport) -> None:
        present = [m for m in members if m.status == "active"]
        talked = {t["npc"] for t in group.talks}
        for quest in self.world.quests.values():
            if quest.done:
                continue
            if quest.kind == "neben" and quest.giver in talked:
                new = [m.id for m in present if m.id not in quest.accepted_by]
                if new:
                    quest.accepted_by += new
                    quest.known = True
                    group.facts.append(f"{self.world.npcs[quest.giver].name} bittet um Hilfe: {quest.name}.")
            if quest.kind == "neben" and not any(m.id in quest.accepted_by for m in present):
                continue
            while (step := quest.next_step()) is not None and self._step_done(step, present, talked):
                step.done = True
                quest.known = True
                group.facts.append(f"Fortschritt – {quest.name}: {step.text}")
                if quest.kind == "haupt" and step.kind != "talk":
                    for player in present:
                        self._xp(player, self.catalog.rules.xp.main_quest_step, group)
            if quest.next_step() is None:
                self._complete(quest, present, group)

    def _step_done(self, step, present: list[Character], talked: set[str]) -> bool:
        if step.kind == "item":
            return any(i.name == step.item_name for m in present for i in ch.all_items(m))
        if step.kind == "defeat":
            enc = self.world.location(step.location).encounter
            return enc is None or enc.state != "feindlich"
        if step.kind == "reach":
            return any(m.location == step.location for m in present)
        if step.kind == "talk":
            return step.npc in talked
        if step.kind == "deliver" and step.npc in talked:
            for member in present:
                item = next((i for i in member.bag if i.name == step.item_name), None)
                if item is not None:
                    remove_from_bag(member, item.id, item.quantity)
                    return True
        return False

    def _complete(self, quest: Quest, present: list[Character], group: GroupReport) -> None:
        quest.done = True
        group.facts.append(f"Auftrag erfüllt: {quest.name}.")
        if quest.kind == "haupt":
            return
        helpers = [m for m in present if m.id in quest.accepted_by] or present
        reward = quest.reward
        for player in helpers:
            self._xp(player, self.catalog.rules.xp.side_quest, group)
            bump(player, "auftraege")
            if reward.affinity and el.gain_affinity(self.catalog, player, reward.affinity):
                label = self.catalog.rules.elements[reward.affinity].label
                group.report(player.id).level_ups.append(f"Affinität {label} {player.affinity[reward.affinity]}")
        if reward.gold:
            share, rest = divmod(reward.gold, len(helpers))
            for n, player in enumerate(helpers):
                amount = share + (1 if n < rest else 0)
                player.gold += amount
                group.report(player.id).gold += amount
        if reward.item:
            self._give_item(helpers[0], self._make(reward.item), helpers[0].location, group)
        if reward.people and reward.people in self.world.peoples:
            people = self.world.peoples[reward.people]
            people.attitude = min(2, people.attitude + 1)
            for npc in self.world.npcs.values():
                if npc.people == people.id:
                    npc.attitude = min(2, npc.attitude + 1)

    # --- XP ----------------------------------------------------------------------

    def _xp(self, player: Character, amount: int, group: GroupReport) -> None:
        gained, levels = ch.add_xp(self.catalog, player, amount, self.state.length,
                                   average_level=self.state.average_level(), turn=self.state.turn)
        rep = group.report(player.id)
        rep.xp += gained
        for event in levels:
            text = f"Stufe {event.level}! +{event.hp_gained} LP"
            if event.attribute:
                text += f", +1 {ATTR_SHORT[event.attribute]}"
            if event.ability_granted:
                text += f", neue Fähigkeit: {self.catalog.abilities[event.ability_granted].name}"
            if event.ability_offered:
                options = " / ".join(self.catalog.abilities[a].name for a in event.ability_offered)
                text += f". Wähle eine Fähigkeit: {options}"
            rep.level_ups.append(text)
            group.facts.append(f"{player.name} erreicht Stufe {event.level}.")


def find_name(player: Character, item_id: str) -> str:
    for item in ch.all_items(player):
        if item.id == item_id:
            return item.name
    return "etwas"

