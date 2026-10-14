"""Loads and validates the hand-written rules data in ``catalog/``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .models import AbilityDef, ClassDef, EnemyCatalog, ItemBase, NameLists, Rules

DEFAULT_CATALOG_DIR = Path(__file__).resolve().parents[2] / "catalog"


@dataclass(frozen=True)
class Catalog:
    rules: Rules
    classes: dict[str, ClassDef]
    abilities: dict[str, AbilityDef]
    items: dict[str, ItemBase]
    names: NameLists
    enemies: EnemyCatalog

    def validate_references(self) -> None:
        """Checks that every id referenced between catalog files exists."""
        for class_id, cls in self.classes.items():
            refs = ([cls.first_ability] if cls.first_ability else []) + cls.second_abilities
            for ability in refs:
                if ability not in self.abilities:
                    raise ValueError(f"Klasse {class_id}: unbekannte Fähigkeit {ability}")
                if self.abilities[ability].class_ != class_id:
                    raise ValueError(f"Fähigkeit {ability} gehört nicht zu {class_id}")
            gear = cls.starting_gear
            for base in [gear.waffe, gear.ruestung, *gear.bag] + ([gear.schild] if gear.schild else []):
                if base not in self.items:
                    raise ValueError(f"Klasse {class_id}: unbekannter Gegenstand {base}")
        for base_id, base in self.items.items():
            for class_id in base.classes or []:
                if class_id not in self.classes:
                    raise ValueError(f"Gegenstand {base_id}: unbekannte Klasse {class_id}")


def _read(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_catalog(directory: Path = DEFAULT_CATALOG_DIR) -> Catalog:
    catalog = Catalog(
        rules=Rules.model_validate(_read(directory / "rules.json")),
        classes={k: ClassDef.model_validate(v) for k, v in _read(directory / "classes.json").items()},
        abilities={k: AbilityDef.model_validate(v) for k, v in _read(directory / "abilities.json").items()},
        items={k: ItemBase.model_validate(v) for k, v in _read(directory / "items.json").items()},
        names=NameLists.model_validate(_read(directory / "names.json")),
        enemies=EnemyCatalog.model_validate(_read(directory / "enemies.json")),
    )
    catalog.validate_references()
    return catalog


@lru_cache(maxsize=1)
def default_catalog() -> Catalog:
    return load_catalog()
