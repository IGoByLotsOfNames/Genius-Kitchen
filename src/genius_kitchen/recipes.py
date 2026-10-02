from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Iterable

from .models import Recipe, normalize_ingredient_name


@dataclass(frozen=True, slots=True)
class RecipeMatch:
    recipe: Recipe
    available: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def coverage(self) -> float:
        return (
            len(self.available) / len(self.recipe.ingredients) if self.recipe.ingredients else 1.0
        )


def load_recipes(path: Path) -> tuple[Recipe, ...]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError(f"Invalid recipe file {path}: expected UTF-8 text") from exc
    return _parse_recipes(content, str(path))


def _parse_recipes(content: str, source: str) -> tuple[Recipe, ...]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid recipe file {source}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"Invalid recipe file {source}: expected an array of recipes")
    recipes: list[Recipe] = []
    for index, item in enumerate(data):
        try:
            recipes.append(Recipe.from_dict(item))
        except ValueError as exc:
            raise ValueError(f"Invalid recipe file {source}, item {index + 1}: {exc}") from exc
    return tuple(recipes)


def load_bundled_recipes() -> tuple[Recipe, ...]:
    resource = files("genius_kitchen").joinpath("data", "recipes.json")
    try:
        content = resource.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError(f"Invalid recipe file {resource}: expected UTF-8 text") from exc
    return _parse_recipes(content, str(resource))


def match_recipes(
    available_ingredients: Iterable[str],
    recipes: Iterable[Recipe],
    *,
    limit: int = 10,
) -> tuple[RecipeMatch, ...]:
    available = {normalize_ingredient_name(item) for item in available_ingredients}
    matches: list[RecipeMatch] = []
    for recipe in recipes:
        present = tuple(item for item in recipe.ingredients if item in available)
        missing = tuple(item for item in recipe.ingredients if item not in available)
        matches.append(RecipeMatch(recipe=recipe, available=present, missing=missing))
    matches.sort(key=lambda item: (-item.coverage, len(item.missing), item.recipe.name))
    return tuple(matches[:limit])
