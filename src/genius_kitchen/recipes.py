from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Iterable

from .models import Recipe


@dataclass(frozen=True, slots=True)
class RecipeMatch:
    recipe: Recipe
    available: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def coverage(self) -> float:
        return len(self.available) / len(self.recipe.ingredients) if self.recipe.ingredients else 1.0


def load_recipes(path: Path) -> tuple[Recipe, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(Recipe.from_dict(item) for item in data)


def load_bundled_recipes() -> tuple[Recipe, ...]:
    resource = files("genius_kitchen").joinpath("data", "recipes.json")
    data = json.loads(resource.read_text(encoding="utf-8"))
    return tuple(Recipe.from_dict(item) for item in data)


def match_recipes(
    available_ingredients: Iterable[str],
    recipes: Iterable[Recipe],
    *,
    limit: int = 10,
) -> tuple[RecipeMatch, ...]:
    available = {item.casefold().strip() for item in available_ingredients}
    matches: list[RecipeMatch] = []
    for recipe in recipes:
        present = tuple(item for item in recipe.ingredients if item in available)
        missing = tuple(item for item in recipe.ingredients if item not in available)
        matches.append(RecipeMatch(recipe=recipe, available=present, missing=missing))
    matches.sort(key=lambda item: (-item.coverage, len(item.missing), item.recipe.name))
    return tuple(matches[:limit])
