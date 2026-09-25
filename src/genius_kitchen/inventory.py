from __future__ import annotations

from datetime import date
from typing import Iterable

from .models import Ingredient


class Inventory:
    def __init__(self, ingredients: Iterable[Ingredient] = ()) -> None:
        self._ingredients = list(ingredients)

    @property
    def ingredients(self) -> tuple[Ingredient, ...]:
        return tuple(sorted(self._ingredients, key=lambda item: item.expires_on))

    def add(self, ingredient: Ingredient) -> None:
        self._ingredients.append(ingredient)

    def remove(self, ingredient: Ingredient) -> None:
        self._ingredients.remove(ingredient)

    def expiring_within(self, days: int, today: date | None = None) -> tuple[Ingredient, ...]:
        if days < 0:
            raise ValueError("Days must be non-negative")
        reference = today or date.today()
        return tuple(
            item
            for item in self.ingredients
            if 0 <= item.days_until_expiry(reference) <= days
        )

    def expired(self, today: date | None = None) -> tuple[Ingredient, ...]:
        reference = today or date.today()
        return tuple(item for item in self.ingredients if item.days_until_expiry(reference) < 0)

    def available_names(self, today: date | None = None) -> set[str]:
        reference = today or date.today()
        return {
            item.name.casefold()
            for item in self._ingredients
            if item.days_until_expiry(reference) >= 0 and item.quantity > 0
        }

