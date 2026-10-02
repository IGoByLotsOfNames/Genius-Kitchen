from __future__ import annotations

import json
from pathlib import Path

from .inventory import Inventory
from .models import Ingredient


class JSONInventoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Inventory:
        try:
            content = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Inventory()
        except UnicodeError as exc:
            raise ValueError(f"Invalid inventory file {self.path}: expected UTF-8 text") from exc
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid inventory file {self.path}: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError(
                f"Invalid inventory file {self.path}: expected an array of ingredients"
            )
        ingredients = []
        for index, item in enumerate(data):
            try:
                ingredients.append(Ingredient.from_dict(item))
            except ValueError as exc:
                raise ValueError(
                    f"Invalid inventory file {self.path}, item {index + 1}: {exc}"
                ) from exc
        return Inventory(ingredients)

    def save(self, inventory: Inventory) -> None:
        content = json.dumps(
            [item.to_dict() for item in inventory.ingredients], indent=2, allow_nan=False
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.path)
