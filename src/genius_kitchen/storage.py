from __future__ import annotations

import json
from pathlib import Path

from .inventory import Inventory
from .models import Ingredient


class JSONInventoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Inventory:
        if not self.path.exists():
            return Inventory()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return Inventory(Ingredient.from_dict(item) for item in data)

    def save(self, inventory: Inventory) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps([item.to_dict() for item in inventory.ingredients], indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

