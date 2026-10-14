"""Text output: chapter with result box, character sheet, map (design §16).

The same Markdown is printed in the local play mode and stored in the
chronicle; the Discord step turns the result box and sheets into embeds.
"""

from __future__ import annotations

from .catalog import Catalog
from .engine import GroupReport, TurnReport
from .models import Character
from .rules import character as ch
from .rules.items import describe, display_name, slots_used
from .state import GameState

def _bar(current: int, maximum: int, full: str, empty: str = "⬛", segments: int = 10) -> str:
    filled = 0 if maximum <= 0 else round(segments * max(0, current) / maximum)
    return full * filled + empty * (segments - filled)


def result_lines(catalog: Catalog, state: GameState, group: GroupReport) -> list[str]:
    lines = []
    for pid in group.players:
        player = state.players.get(pid)
        rep = group.per_player.get(pid)
        if player is None:
            continue
        parts: list[str] = []
        if rep:
            parts += [f"🎲 {r}" for r in rep.rolls]
            if rep.attacks:
                parts.append(f"⚔️ {rep.hits}/{rep.attacks} Treffer, {rep.damage} Schaden")
            if rep.healed:
                parts.append(f"💚 +{rep.healed} LP")
        parts.append(f"❤️ {player.hp} / {ch.max_hp(catalog, player)}")
        if rep:
            if rep.xp:
                parts.append(f"✨ +{rep.xp} EP")
            if rep.gold:
                parts.append(f"💰 {rep.gold:+d}")
            if rep.items:
                parts.append("🎒 " + ", ".join(rep.items))
            parts += [f"⬆️ {u}" if not u.startswith(("🪦", "Affinität")) else u for u in rep.level_ups]
        lines.append(f"**{player.name}**: " + " · ".join(parts))
    if group.enemies:
        lines.append("Gegner: " + ", ".join(group.enemies))
    return lines


def chapter_text(catalog: Catalog, state: GameState, report: TurnReport, mention=lambda p: f"@{p.name}") -> str:
    out = [f"## ☀️ Tag {report.turn}"] + [f"*{text}*" for text in report.announcements]
    for group in report.groups:
        players = [state.players[p] for p in group.players if p in state.players]
        ends = group.end_locations or {group.location}
        location = state.world.location(next(iter(ends)) if len(ends) == 1 else group.location)
        out.append(f"### 📍 {state.world.region_of(location.id).name} – {location.name}")
        mentions = [mention(p) for p in players if p.status != "camp"]
        if mentions:
            out.append(" ".join(mentions))
        if group.narration:
            out.append(group.narration)
        box = result_lines(catalog, state, group)
        if box:
            out.append("> **Ergebnis**\n" + "\n".join(f"> {line}" for line in box))
        out += [f"-# ℹ️ {note}" for note in group.ooc]
    out += [f"-# ℹ️ {note}" for note in report.ooc]
    return "\n\n".join(out) + "\n"


def sheet_text(catalog: Catalog, state: GameState, player: Character) -> str:
    rules = catalog.rules
    element = rules.elements[player.element]
    max_hp = ch.max_hp(catalog, player)
    next_xp = ch.xp_for_next_level(catalog, player, state.length)
    start = ch.level_start_xp(catalog, player.level, state.length)
    if next_xp is None:
        xp_line = f"✨ {player.xp} EP (höchste Stufe)"
    else:
        xp_line = f"✨ {_bar(player.xp - start, next_xp - start, '🟨')} {player.xp} / {next_xp} EP"
    status = {"camp": " · ⛺ Im Lager", "left": " · hat das Abenteuer verlassen"}.get(player.status, "")
    if player.down:
        status += " · Kampfunfähig"
    profile = ch.attack_profile(catalog, player)
    attrs = " · ".join(f"{label} {ch.attribute(catalog, player, attr):+d}".replace("+0", "0")
                       for attr, label in (("staerke", "STÄ"), ("geschick", "GES"), ("verstand", "VER")))
    affinity = " · ".join(f"{rules.elements[e].emoji} {v}" for e, v in player.affinity.items() if v) or "–"
    abilities = " · ".join(
        f"{catalog.abilities[a].name} " + ("✔" if ch.ability_ready(player, a) else f"⏳ {player.cooldowns[a]} Tage")
        for a in player.abilities
    ) or "–"
    equipment = " · ".join(describe(catalog, i) for i in vars(player.equipment).values() if i is not None) or "–"
    bag = " · ".join(display_name(catalog, i) for i in player.bag) or "leer"
    location = state.world.location(player.location).name if player.location in state.world.locations else player.location
    companions = [p.name for p in state.active_players() if p.location == player.location and p.id != player.id]
    lines = [
        f"{player.class_label} · {element.emoji} {element.label}",
        f"**{player.name} · Stufe {player.level}**{status}",
        f"❤️ {_bar(player.hp, max_hp, '🟥')} {player.hp} / {max_hp} LP",
        xp_line,
        f"⚔️ Schaden {profile.damage_label} · 🛡️ Rüstungswert {ch.armor_value(catalog, player)} · 💰 Gold {player.gold}",
        f"Attribute: {attrs} | Affinität: {affinity} | Fähigkeiten: {abilities}",
        f"Ausrüstung: {equipment}",
        f"Rucksack ({slots_used(catalog, player)} / {rules.bag_slots}): {bag}",
    ]
    if player.grave:
        grave_loc = state.world.location(player.grave.location).name
        lines.append(f"🪦 Grab: {grave_loc} – {player.grave.gold} Gold, {len(player.grave.items)} Gegenstände")
    lines.append(f"📍 {location}" + (f" · mit {', '.join(companions)}" if companions else ""))
    return "\n".join(lines)


def map_text(state: GameState) -> str:
    world = state.world
    lines = [f"**{world.name}** – {world.premise}"]
    for region in world.regions.values():
        locations = [loc for loc in world.locations.values() if loc.region == region.id and loc.discovered]
        if not locations:
            continue
        lines.append(f"\n**{region.name}**")
        for loc in locations:
            here = [p.name for p in state.active_players() if p.location == loc.id]
            marks = (" 🛏️" if loc.rest_point else "") + (" ⚠️" if loc.encounter and loc.encounter.state == "feindlich" and loc.encounter.seen_turn else "")
            exits = ", ".join(world.location(c.to).name for c in world.visible_connections(loc.id))
            lines.append(f"- {loc.name}{marks}" + (f" – {', '.join(here)}" if here else "") + f"  → {exits}")
    return "\n".join(lines)


def quest_log_text(catalog: Catalog, state: GameState) -> str:
    world = state.world
    elements = catalog.rules.elements
    shards = []
    for plan_region in world.regions.values():
        if not plan_region.elements or plan_region.id == "final":
            continue
        element = plan_region.elements[0]
        shards.append(f"{elements[element].emoji} {'✅' if element in world.seal else '⬜'}")
    lines = [f"📜 **{world.name}**", world.premise]
    if shards:
        lines.append(f"**Siegel**: {' · '.join(shards)} ({len(set(world.seal))} / {world.shards_needed} Splitter)")
    for quest in world.quests.values():
        if not quest.known:
            continue
        icon = "✅" if quest.done else ("⭐" if quest.kind == "haupt" else "📌")
        line = f"{icon} **{quest.name}**"
        if quest.kind == "neben" and quest.accepted_by:
            names = [state.players[p].name for p in quest.accepted_by if p in state.players]
            line += f" ({', '.join(names)})"
        lines.append(line)
        if not quest.done:
            for step in quest.steps:
                lines.append(f"  {'✔' if step.done else '▫'} {step.text}")
                if not step.done:
                    break
    return "\n".join(lines)


STAT_LABELS = [
    ("gegner_besiegt", "Die meisten besiegten Gegner"),
    ("tode", "Die meisten Tode"),
    ("gold_erbeutet", "Das meiste erbeutete Gold"),
    ("verschenkt", "Die meisten verschenkten Gegenstände"),
    ("auftraege", "Die meisten erfüllten Aufträge"),
    ("orte_entdeckt", "Die meisten entdeckten Orte"),
    ("untaetig", "Die meisten untätigen Tage"),
]


def stats_text(state: GameState) -> str:
    players = list(state.players.values())
    lines = [f"## 🏆 Die Chronik in Zahlen – {state.turn} Tage"]
    for key, label in STAT_LABELS:
        best = max(players, key=lambda p: p.stats.get(key, 0), default=None)
        if best is not None and best.stats.get(key, 0) > 0:
            lines.append(f"**{label}**: {best.name} ({best.stats[key]})")
    lines.append("**Höchste Stufe**: " + ", ".join(f"{p.name} ({p.level})" for p in sorted(players, key=lambda p: -p.level)[:3]))
    return "\n".join(lines)
