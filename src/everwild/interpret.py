"""Interpret: player text → one action per player (design §3, §18).

With an LLM, the prompt in ``prompts/interpret.md`` is used. Without one,
``offline_actions`` maps the text with simple German keyword rules — good
enough to test the rules and the local play mode.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel, Field

from .actions import Action, ActionList, JoinInfo
from .catalog import Catalog
from .llm import LLM, ask_model
from .models import Element

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


class JoinReply(JoinInfo):
    is_join: bool = Field(description="True, wenn die Person mitspielen will")


# --- LLM ---------------------------------------------------------------------


def llm_actions(llm: LLM, scene: dict, texts: dict[str, str]) -> list[Action]:
    payload = {"szene": scene, "texte": texts}
    reply = ask_model(llm, prompt("interpret"), json.dumps(payload, ensure_ascii=False, indent=1), ActionList)
    by_player = {a.player_id: a for a in reply.actions if a.player_id in texts}
    return [by_player.get(pid) or Action(player_id=pid, kind="nichts", summary="zögert") for pid in texts]


def llm_join(llm: LLM, catalog: Catalog, text: str) -> JoinReply:
    classes = {cid: c.label for cid, c in catalog.classes.items() if c.selectable}
    payload = {"klassen": classes, "nachricht": text}
    return ask_model(llm, prompt("join"), json.dumps(payload, ensure_ascii=False), JoinReply)


# --- offline -----------------------------------------------------------------


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = text.replace("ß", "ss")
    return "".join(c for c in text if not unicodedata.combining(c))


def _find(text: str, candidates: list[dict], key: str = "name") -> str | None:
    """The candidate whose name (or a word of it, ≥ 4 letters) appears in the text."""
    norm = _norm(text)
    best, best_len = None, 0
    for cand in candidates:
        name = _norm(cand[key])
        words = [name] + [w for w in re.split(r"[\s\-–„“\"']+", name) if len(w) >= 4]
        for word in words:
            if word and word in norm and len(word) > best_len:
                best, best_len = cand["id"], len(word)
    return best


_VERBS: list[tuple[str, str]] = [
    (r"\bfolge\b|\bhinterher\b", "folgen"),
    (r"\bfliehe|\bfluecht|\brenn\w* weg|\bhaue? ab\b", "fliehen"),
    (r"\bgrab\b", "grab_bergen"),
    (r"\bverkauf", "verkaufen"),
    (r"\bkauf", "kaufen"),
    (r"\bgib\b|\bgebe\b|\bueberreich|\bschenk", "geben"),
    (r"\btrink|\bbenutz|\blese? die schriftrolle|\bverwende", "gegenstand"),
    (r"\bheb\w* .*auf\b|\bnehme? .*mit\b|\bsammle", "aufheben"),
    (r"\bverteidig|\bschuetz|\bdecke?\b", "verteidigen"),
    (r"\bgreif\w* an|\bangriff|\bschlag|\bkaempf|\battackier|\btoet|\bhau\b|\bstech|\bschiess", "angreifen"),
    (r"\buntersuch|\bdurchsuch|\bsuche\b|\bschau\w* .*an|\bbetrachte|\bdurchstoeber", "untersuchen"),
    (r"\bsprech|\bsprich|\brede\b|\bfrag|\bsag\w*|\bbegruess|\bunterhalt", "sprechen"),
    (r"\braste|\bschlaf|\bruh\w* (mich )?aus|\bbete\b|\bausruhen", "rasten"),
    (r"\bgeh\w*\b|\blauf|\breise|\bwander|\bmach\w* mich auf|\bbetrete|\bzurueck|\bkehre", "bewegen"),
    (r"\bkletter|\bspring|\bschleich|\bknack|\bklettere|\bschwimm", "probe"),
]


def offline_action(catalog: Catalog, scene: dict, player_id: str, text: str) -> Action:
    norm = _norm(text)
    me = next(p for p in scene["spieler"] if p["id"] == player_id)
    others = [p for p in scene["spieler"] if p["id"] != player_id]
    items = me["rucksack"] + me["ausruestung"]
    action = Action(player_id=player_id, kind="nichts", summary=text.strip().rstrip(".!")[:120])

    ability = _find(text, [{"id": a["id"], "name": a["name"]} for a in me["faehigkeiten"]])
    if ability:
        action.kind, action.ability = "faehigkeit", ability
        action.target = (_find(text, scene["gegner"]) or _find(text, others) or _find(text, scene["nsc"])
                         or _find(text, scene["ort"]["ausgaenge"]))
        if ability == "erkenntnis":
            action.speech = text.strip()
        return action

    for pattern, kind in _VERBS:
        if re.search(pattern, norm):
            action.kind = kind  # type: ignore[assignment]
            break

    if action.kind == "folgen":
        action.target = _find(text, others)
    elif action.kind in ("angreifen",):
        action.target = _find(text, scene["gegner"]) or _find(text, scene["nsc"])
    elif action.kind == "verteidigen":
        action.target = _find(text, others)
    elif action.kind == "gegenstand":
        action.item = _find(text, items)
        action.target = _find(text, others)
    elif action.kind == "geben":
        action.item = _find(text, items)
        action.target = _find(text, others)
    elif action.kind == "untersuchen":
        action.target = _find(text, scene["ort"]["merkmale"])
    elif action.kind == "sprechen":
        action.target = _find(text, scene["nsc"]) or (scene["nsc"][0]["id"] if scene["nsc"] else None)
        quoted = re.findall(r"[„\"“](.+?)[“\"”]", text)
        action.speech = quoted[0] if quoted else text.strip()
        if re.search(r"\bueberzeug|\bueberred|\bfeilsch|\bbluff|\brabatt|\bbillig", norm):
            action.attribute, action.difficulty = "verstand", "mittel"
    elif action.kind == "kaufen":
        action.target = _find(text, scene["nsc"]) or next((n["id"] for n in scene["nsc"] if n["angebot"]), None)
        offers = [{"id": o["basis"], "name": o["name"]} for n in scene["nsc"] for o in n["angebot"]]
        action.item = _find(text, offers)
    elif action.kind == "verkaufen":
        action.target = next((n["id"] for n in scene["nsc"] if n["angebot"]), None)
        action.item = _find(text, items)
    elif action.kind == "aufheben":
        action.item = _find(text, scene["ort"]["gegenstaende_am_boden"]) or (
            scene["ort"]["gegenstaende_am_boden"][0]["id"] if scene["ort"]["gegenstaende_am_boden"] else None)
    elif action.kind == "bewegen":
        action.target = _find(text, scene["ort"]["ausgaenge"])
        if action.target is None:
            action.kind = "nichts"
    elif action.kind == "probe":
        action.attribute = "staerke" if re.search(r"kletter|spring|schwimm", norm) else "geschick"
        action.difficulty = "mittel"
    if action.kind == "nichts" and scene["gegner"] and re.search(r"\bkampf|\bwaffe|\bschwert", norm):
        action.kind = "angreifen"
    return action


def offline_actions(catalog: Catalog, scene: dict, texts: dict[str, str]) -> list[Action]:
    return [offline_action(catalog, scene, pid, text) for pid, text in texts.items()]


_CLASS_WORDS: dict[str, list[str]] = {
    "krieger": ["krieger", "soeldner", "paladin", "kaempfer", "ritter", "barbar"],
    "waldlaeufer": ["waldlaeufer", "jaeger", "spaeher", "bogenschuetz", "ranger"],
    "magier": ["magier", "zauberer", "hexer", "hexe", "zauberin", "mage"],
    "kleriker": ["kleriker", "priester", "heiler", "moench", "nonne"],
    "schurke": ["schurke", "schurkin", "dieb", "assassin", "meuchel"],
    "barde": ["barde", "bardin", "spielmann", "musikant", "saenger"],
}
_ELEMENT_WORDS: dict[str, list[str]] = {
    "feuer": ["feuer", "flamme", "glut"], "wasser": ["wasser", "eis", "frost", "nebel"],
    "erde": ["erde", "stein", "fels"], "luft": ["luft", "sturm", "wind", "blitz"],
    "licht": ["licht", "sonne", "heilig"], "schatten": ["schatten", "nacht", "dunkel"],
    "stahl": ["stahl", "ohne element"],
}


def offline_join(catalog: Catalog, text: str) -> JoinReply:
    norm = _norm(text)
    class_id = next((cid for cid, words in _CLASS_WORDS.items() if any(re.search(rf"\b{w}", norm) for w in words)), None)
    class_label = None
    if class_id:
        match = re.search(r"\b(\w*(?:" + "|".join(_CLASS_WORDS[class_id]) + r")\w*)", norm)
        if match and match.group(1).endswith("in"):
            class_label = catalog.classes[class_id].label_f
    element: Element | None = next(  # type: ignore[assignment]
        (e for e, words in _ELEMENT_WORDS.items() if any(re.search(rf"\b{w}", norm) for w in words)), None)
    name_match = re.search(r"\b(?:ich bin|ich hei(?:ß|ss)e|mein name ist)\s+([A-ZÄÖÜ][\wäöüß]+)", text, re.IGNORECASE)
    name = name_match.group(1) if name_match else None
    if name and _norm(name) in ("ein", "eine", "der", "die"):
        name = None
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    background = sentences[1] if len(sentences) > 1 else None
    is_join = bool(name_match or class_id or re.search(r"mitspiel|beitret|dabei|mitmach", norm))
    return JoinReply(is_join=is_join, name=name, class_id=class_id, class_label=class_label,
                     element=element, background=background)


class Interpreter(BaseModel):
    """Picks the LLM or the offline rules."""

    model_config = {"arbitrary_types_allowed": True}
    llm: object | None = None

    def actions(self, catalog: Catalog, scene: dict, texts: dict[str, str]) -> list[Action]:
        if not texts:
            return []
        if self.llm is None:
            return offline_actions(catalog, scene, texts)
        return llm_actions(self.llm, scene, texts)  # type: ignore[arg-type]

    def join(self, catalog: Catalog, text: str) -> JoinReply:
        if self.llm is None:
            return offline_join(catalog, text)
        return llm_join(self.llm, catalog, text)  # type: ignore[arg-type]
