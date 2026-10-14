"""Discord messages: chapter, result embeds, character sheets, quest log (design §16)."""

from __future__ import annotations

from .catalog import Catalog
from .engine import TurnReport
from .render import group_location, player_result_parts, quest_entries, seal_line, sheet_parts, stats_text
from .state import GameState

COLORS = {"feuer": 0xE8613C, "wasser": 0x3C8EE8, "erde": 0x8B6B3E, "luft": 0x9AD1E8,
          "licht": 0xF2D675, "schatten": 0x8A5CD6, "stahl": 0x99AAB5}
CONTENT_LIMIT = 2000
FIELD_LIMIT = 1024


def split_text(text: str, limit: int = CONTENT_LIMIT) -> list[str]:
    """Splits at paragraph boundaries (sentences if a paragraph is too long)."""
    parts: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        pieces = [paragraph]
        if len(paragraph) > limit:
            pieces, chunk = [], ""
            for sentence in paragraph.replace(". ", ".\n").split("\n"):
                if len(chunk) + len(sentence) + 1 > limit and chunk:
                    pieces.append(chunk)
                    chunk = ""
                chunk = f"{chunk} {sentence}".strip()
            pieces.append(chunk)
        for piece in pieces:
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) > limit and current:
                parts.append(current)
                current = piece[:limit]
            else:
                current = candidate[:limit]
    if current:
        parts.append(current)
    return parts


def _clip(text: str, limit: int = FIELD_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def mention(player_id: str) -> str:
    return f"<@{player_id}>"


def turn_messages(catalog: Catalog, state: GameState, report: TurnReport) -> list[dict]:
    """The daily chapter: a header, then per group the story with a result embed."""
    header = f"## ☀️ Tag {report.turn}"
    if report.announcements:
        header += "\n\n" + "\n\n".join(f"*{a}*" for a in report.announcements)
    messages = [{"content": header[:CONTENT_LIMIT], "embeds": [], "mentions": False}]
    for group in report.groups:
        players = [state.players[p] for p in group.players if p in state.players]
        location = group_location(state, group)
        region = state.world.region_of(location.id)
        mentions = " ".join(mention(p.id) for p in players if p.status != "camp")
        text = f"### 📍 {region.name} – {location.name}\n{mentions}\n\n{group.narration}"
        if group.ooc:
            text += "\n" + "\n".join(f"-# ℹ️ {note}" for note in group.ooc)
        fields = [{"name": p.name, "value": _clip("\n".join(player_result_parts(catalog, state, group, p.id))), "inline": True}
                  for p in players]
        if group.enemies:
            fields.append({"name": "Gegner", "value": _clip("\n".join(group.enemies)), "inline": False})
        embed = {"title": "Ergebnis", "color": COLORS.get(region.elements[0] if region.elements else "stahl"),
                 "fields": fields[:25]}
        parts = split_text(text)
        for n, part in enumerate(parts):
            last = n == len(parts) - 1
            messages.append({"content": part, "embeds": [embed] if last and fields else [], "mentions": n == 0})
    if report.ooc:
        notes = "\n".join(f"-# ℹ️ {note}" for note in report.ooc)
        messages += [{"content": part, "embeds": [], "mentions": False} for part in split_text(notes)]
    return messages


def sheet_embed(catalog: Catalog, state: GameState, player) -> dict:
    s = sheet_parts(catalog, state, player)
    fields = [
        {"name": "⚔️ Schaden", "value": s["damage"], "inline": True},
        {"name": "🛡️ Rüstungswert", "value": s["armor"], "inline": True},
        {"name": "💰 Gold", "value": s["gold"], "inline": True},
        {"name": "Attribute", "value": "\n".join(s["attributes"]), "inline": True},
        {"name": "Affinität", "value": "\n".join(s["affinity"]) or "–", "inline": True},
        {"name": "Fähigkeiten", "value": _clip("\n".join(s["abilities"]) or "–"), "inline": True},
        {"name": "Ausrüstung", "value": _clip(" · ".join(s["equipment"]) or "–"), "inline": False},
        {"name": s["bag_label"], "value": _clip(" · ".join(s["bag"]) or "leer"), "inline": False},
    ]
    if s["grave"]:
        fields.append({"name": "🪦 Grab", "value": s["grave"], "inline": False})
    return {"author": {"name": s["author"]}, "title": s["title"], "description": f"{s['hp_line']}\n{s['xp_line']}",
            "color": COLORS[s["element"]], "fields": fields, "footer": {"text": _clip(s["footer"], 2048)}}


def quest_log_embed(catalog: Catalog, state: GameState) -> dict:
    world = state.world
    description = world.premise
    seal = seal_line(catalog, state)
    if seal:
        description += f"\n\n{seal}"
    fields = []
    entries = quest_entries(state)
    open_entries = [e for e in entries if e[1]] + [e for e in entries if not e[1]]
    for title, steps in open_entries:
        fields.append({"name": _clip(title, 256), "value": _clip("\n".join(steps) or "erfüllt")})
    for region in world.regions.values():
        lines = []
        for loc in world.locations.values():
            if loc.region != region.id or not loc.discovered:
                continue
            here = [p.name for p in state.active_players() if p.location == loc.id]
            mark = " 🛏️" if loc.rest_point else ""
            lines.append(f"{loc.name}{mark}" + (f" – {', '.join(here)}" if here else ""))
        if lines:
            fields.append({"name": f"🗺️ {region.name}", "value": _clip("\n".join(lines))})
    embed = {"title": f"📜 {world.name}", "description": description[:4096], "color": COLORS["licht"], "fields": []}
    total = len(embed["title"]) + len(embed["description"])
    for field in fields[:25]:
        size = len(field["name"]) + len(field["value"])
        if total + size > 5800:
            break
        embed["fields"].append(field)
        total += size
    return embed


def howto_text(catalog: Catalog) -> str:
    classes = ", ".join(c.label for c in catalog.classes.values() if c.selectable)
    elements = " · ".join(f"{e.emoji} {e.label}" for e in catalog.rules.elements.values())
    return (
        "## So spielst du mit\n"
        "Schreib einfach hier in den Kanal, was deine Figur tun will – ganz normal auf Deutsch. "
        "Jeden Abend gegen 20 Uhr erzählt der Chronist, wie es weitergeht.\n\n"
        "**Mitmachen**: „Ich bin Brakka, eine Kriegerin des Feuers. Eine vernarbte Söldnerin aus dem Norden.“\n"
        f"**Klassen**: {classes}\n"
        f"**Elemente**: {elements} (Stahl = ohne Element)\n"
        "**Jeden Tag eine Handlung**, z. B. „Ich gehe in den Finsterwald“, „Ich frage die Wirtin nach dem Turm“ "
        "oder „Ich greife den Oger mit der Axt an“. Klasse und Element kannst du in den ersten drei Tagen noch wechseln.\n"
        "**Nicht im Spiel** reden: Nachricht mit `//` beginnen.\n"
        "**Charakterbögen und Questlog** stehen im Thread 📖 Weltbuch unter dieser Nachricht."
    )


def topic_text(state: GameState) -> str:
    world = state.world
    if state.finished:
        return f"Das Abenteuer in {world.name} ist vollbracht · {state.turn} Tage"
    return f"Tag {state.turn} · nächste Runde ca. 20 Uhr · Siegel: {len(set(world.seal))} / {world.shards_needed} Splitter"


def prologue_messages(state: GameState) -> list[dict]:
    text = f"# {state.world.name}\n\n{state.world.premise}\n\nDas Abenteuer beginnt. Wer mitspielen will, stellt sich einfach vor."
    return [{"content": part, "embeds": [], "mentions": False} for part in split_text(text)]


def finale_messages(state: GameState, epilogue_text: str) -> list[dict]:
    texts = split_text(epilogue_text) + split_text(stats_text(state))
    return [{"content": part, "embeds": [], "mentions": False} for part in texts]
