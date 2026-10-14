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


def player_result_parts(catalog: Catalog, state: GameState, group: GroupReport, pid: str) -> list[str]:
    """The numbers of one player in the result box (design §16)."""
    player = state.players[pid]
    rep = group.per_player.get(pid)
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
    return parts


def result_lines(catalog: Catalog, state: GameState, group: GroupReport) -> list[str]:
    lines = [f"**{state.players[pid].name}**: " + " · ".join(player_result_parts(catalog, state, group, pid))
             for pid in group.players if pid in state.players]
    if group.enemies:
        lines.append("Gegner: " + ", ".join(group.enemies))
    return lines


def group_location(state: GameState, group: GroupReport):
    ends = group.end_locations or {group.location}
    return state.world.location(next(iter(ends)) if len(ends) == 1 else group.location)


def chapter_text(catalog: Catalog, state: GameState, report: TurnReport, mention=lambda p: f"@{p.name}") -> str:
    out = [f"## ☀️ Tag {report.turn}"] + [f"*{text}*" for text in report.announcements]
    for group in report.groups:
        players = [state.players[p] for p in group.players if p in state.players]
        location = group_location(state, group)
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


def sheet_parts(catalog: Catalog, state: GameState, player: Character) -> dict:
    """Everything on a character sheet (design §16, layout 5)."""
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
    location = state.world.location(player.location).name if player.location in state.world.locations else player.location
    companions = [p.name for p in state.active_players() if p.location == player.location and p.id != player.id]
    grave = None
    if player.grave:
        grave_loc = state.world.location(player.grave.location).name
        grave = f"{grave_loc} – {player.grave.gold} Gold, {len(player.grave.items)} Gegenstände"
    return {
        "element": player.element,
        "author": f"{player.class_label} · {element.emoji} {element.label}",
        "title": f"{player.name} · Stufe {player.level}{status}",
        "hp_line": f"❤️ {_bar(player.hp, max_hp, '🟥')} {player.hp} / {max_hp} LP",
        "xp_line": xp_line,
        "damage": ch.attack_profile(catalog, player).damage_label,
        "armor": str(ch.armor_value(catalog, player)),
        "gold": str(player.gold),
        "attributes": [f"{label} {ch.attribute(catalog, player, attr):+d}".replace("+0", "0")
                       for attr, label in (("staerke", "STÄ"), ("geschick", "GES"), ("verstand", "VER"))],
        "affinity": [f"{rules.elements[e].emoji} {v}" for e, v in player.affinity.items() if v],
        "abilities": [f"{catalog.abilities[a].name} " + ("✔" if ch.ability_ready(player, a) else f"⏳ {player.cooldowns[a]} Tage")
                      for a in player.abilities],
        "equipment": [describe(catalog, i) for i in vars(player.equipment).values() if i is not None],
        "bag_label": f"Rucksack ({slots_used(catalog, player)} / {rules.bag_slots})",
        "bag": [display_name(catalog, i) for i in player.bag],
        "grave": grave,
        "footer": f"📍 {location}" + (f" · mit {', '.join(companions)}" if companions else ""),
    }


def sheet_text(catalog: Catalog, state: GameState, player: Character) -> str:
    s = sheet_parts(catalog, state, player)
    lines = [
        s["author"],
        f"**{s['title']}**",
        s["hp_line"],
        s["xp_line"],
        f"⚔️ Schaden {s['damage']} · 🛡️ Rüstungswert {s['armor']} · 💰 Gold {s['gold']}",
        f"Attribute: {' · '.join(s['attributes'])} | Affinität: {' · '.join(s['affinity']) or '–'}"
        f" | Fähigkeiten: {' · '.join(s['abilities']) or '–'}",
        f"Ausrüstung: {' · '.join(s['equipment']) or '–'}",
        f"{s['bag_label']}: {' · '.join(s['bag']) or 'leer'}",
    ]
    if s["grave"]:
        lines.append(f"🪦 Grab: {s['grave']}")
    lines.append(s["footer"])
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


def seal_line(catalog: Catalog, state: GameState) -> str | None:
    world = state.world
    shards = []
    for region in world.regions.values():
        if not region.elements or region.id == "final":
            continue
        element = region.elements[0]
        shards.append(f"{catalog.rules.elements[element].emoji} {'✅' if element in world.seal else '⬜'}")
    if not shards:
        return None
    return f"**Siegel**: {' · '.join(shards)} ({len(set(world.seal))} / {world.shards_needed} Splitter)"


def quest_entries(state: GameState) -> list[tuple[str, list[str]]]:
    """Known quests as (title, step lines); done quests without steps."""
    entries = []
    for quest in state.world.quests.values():
        if not quest.known:
            continue
        icon = "✅" if quest.done else ("⭐" if quest.kind == "haupt" else "📌")
        title = f"{icon} {quest.name}"
        if quest.kind == "neben" and quest.accepted_by:
            names = [state.players[p].name for p in quest.accepted_by if p in state.players]
            title += f" ({', '.join(names)})"
        lines = []
        if not quest.done:
            for step in quest.steps:
                lines.append(f"{'✔' if step.done else '▫'} {step.text}")
                if not step.done:
                    break
        entries.append((title, lines))
    return entries


def quest_log_text(catalog: Catalog, state: GameState) -> str:
    world = state.world
    lines = [f"📜 **{world.name}**", world.premise]
    seal = seal_line(catalog, state)
    if seal:
        lines.append(seal)
    for title, steps in quest_entries(state):
        lines.append(f"**{title}**")
        lines += [f"  {step}" for step in steps]
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
