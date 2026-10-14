"""The fixed list of actions a player's text is mapped to (design §3, §18).

The Interpret step (LLM or offline) produces one ``Action`` per player.
Python then checks every id against the scene and carries it out.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .models import Attribute, Element

ActionKind = Literal[
    "bewegen",       # target: location id
    "folgen",        # target: player id
    "angreifen",     # target: enemy id (or null)
    "faehigkeit",    # ability; target: enemy, player, npc or location id
    "verteidigen",   # target: ally player id (or null)
    "gegenstand",    # item: item id; target: player id (or null)
    "geben",         # item: item id; target: player id
    "untersuchen",   # target: feature id
    "sprechen",      # target: npc id; speech
    "rasten",
    "fliehen",
    "kaufen",        # target: npc id; item: item base from the shop
    "verkaufen",     # target: npc id; item: item id
    "aufheben",      # item: id of an item lying at the location
    "grab_bergen",
    "probe",         # attribute + difficulty: anything else that is uncertain
    "nichts",        # hesitate / nothing sensible
]
Difficulty = Literal["leicht", "mittel", "schwer", "heroisch"]

ACTION_LABELS: dict[str, str] = {
    "bewegen": "geht", "folgen": "folgt", "angreifen": "greift an", "faehigkeit": "setzt eine Fähigkeit ein",
    "verteidigen": "verteidigt", "gegenstand": "benutzt einen Gegenstand", "geben": "gibt",
    "untersuchen": "untersucht", "sprechen": "spricht", "rasten": "rastet", "fliehen": "flieht",
    "kaufen": "kauft", "verkaufen": "verkauft", "aufheben": "hebt auf", "grab_bergen": "birgt das Grab",
    "probe": "versucht etwas", "nichts": "zögert",
}


class JoinInfo(BaseModel):
    name: str | None = Field(description="Name der Figur, oder null wenn keiner genannt")
    class_id: str | None = Field(description="Klassen-ID aus der Liste, oder null wenn keine passt")
    class_label: str | None = Field(description="Wortform der Klasse, z. B. 'Kriegerin', oder null")
    element: Element | None = Field(description="Startelement, oder null wenn keines genannt")
    background: str | None = Field(description="Ein Satz zu Aussehen oder Herkunft, oder null")


class Action(BaseModel):
    player_id: str
    kind: ActionKind
    target: str | None = Field(default=None, description="ID aus der Szene, je nach Aktion")
    ability: str | None = Field(default=None, description="Fähigkeits-ID bei 'faehigkeit'")
    item: str | None = Field(default=None, description="Gegenstands-ID (oder Basis-ID beim Kaufen)")
    speech: str | None = Field(default=None, description="Was die Figur sagt oder fragt (wörtlich)")
    attribute: Attribute | None = Field(default=None, description="Bei einer Probe: welches Attribut")
    difficulty: Difficulty | None = Field(default=None, description="Bei einer Probe: wie schwer")
    equip: list[str] = Field(default_factory=list, description="IDs, die vorher angelegt werden (kostenlos)")
    summary: str = Field(default="", description="Kurz auf Deutsch: was die Figur versucht")
    join: JoinInfo | None = Field(default=None, description="Nur bei einer Beitrittsnachricht")
    new_class: str | None = Field(default=None, description="Wunsch nach Klassenwechsel, Klassen-ID")
    new_element: Element | None = Field(default=None, description="Wunsch nach anderem Startelement")
    ability_choice: str | None = Field(default=None, description="Gewählte zweite Fähigkeit, ID")
    attribute_choice: Attribute | None = Field(default=None, description="Gewähltes Attribut für die nächste Steigerung")
    leave: bool = Field(default=False, description="Will das Abenteuer endgültig verlassen")


class ActionList(BaseModel):
    actions: list[Action]


def strict_schema(model: type[BaseModel]) -> dict:
    """Turns a pydantic schema into one OpenAI accepts with ``strict: true``:
    every property required, no additional properties, no defaults.
    """
    schema = model.model_json_schema()

    def fix(node):
        if isinstance(node, dict):
            node.pop("default", None)
            node.pop("title", None)
            if "$ref" in node:  # strict mode allows no keywords next to $ref
                for key in [k for k in node if k != "$ref"]:
                    node.pop(key)
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for value in node.values():
                fix(value)
        elif isinstance(node, list):
            for value in node:
                fix(value)

    fix(schema)
    return schema
