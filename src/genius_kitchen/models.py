from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def normalize_ingredient_name(value: str) -> str:
    """Return the common identity used for pantry and recipe ingredients."""
    name = _string(value, "Ingredient name").strip()
    if not name:
        raise ValueError("Ingredient name cannot be empty")
    return name.casefold()


def _record(value: object, fields: tuple[str, ...], kind: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{kind} must be an object")
    missing = [field for field in fields if field not in value]
    if missing:
        raise ValueError(f"{kind} is missing required fields: {', '.join(missing)}")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{field} must be a list or tuple of strings")
    return tuple(_string(item, f"{field}[{index}]") for index, item in enumerate(value))


def _positive_quantity(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Quantity must be a number")
    try:
        finite = isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("Quantity must be finite")
    if value <= 0:
        raise ValueError("Quantity must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Ingredient:
    name: str
    quantity: float
    unit: str
    expires_on: date
    category: str = "Other"

    def __post_init__(self) -> None:
        normalize_ingredient_name(self.name)
        _positive_quantity(self.quantity)
        _string(self.unit, "Unit")
        _string(self.category, "Category")
        if type(self.expires_on) is not date:
            raise ValueError("Expiry must be a date")
        # Normalize once during construction; the resulting object remains frozen.
        object.__setattr__(self, "name", self.name.strip())

    def days_until_expiry(self, today: date | None = None) -> int:
        return (self.expires_on - (today or date.today())).days

    def to_dict(self) -> dict[str, str | float]:
        value = asdict(self)
        value["expires_on"] = self.expires_on.isoformat()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Ingredient":
        value = _record(value, ("name", "quantity", "unit", "expires_on"), "Ingredient")
        expiry = _string(value["expires_on"], "Expiry")
        try:
            expires_on = date.fromisoformat(expiry)
        except ValueError as exc:
            raise ValueError("Expiry must be a valid ISO date") from exc
        return cls(
            name=_string(value["name"], "Ingredient name"),
            quantity=_positive_quantity(value["quantity"]),
            unit=_string(value["unit"], "Unit"),
            expires_on=expires_on,
            category=_string(value.get("category", "Other"), "Category"),
        )


@dataclass(frozen=True, slots=True)
class Recipe:
    name: str
    ingredients: tuple[str, ...]
    instructions: tuple[str, ...]
    source_url: str | None = None

    def __post_init__(self) -> None:
        _string(self.name, "Recipe name")
        ingredients = _strings(self.ingredients, "Recipe ingredients")
        instructions = _strings(self.instructions, "Recipe instructions")
        if self.source_url is not None:
            _string(self.source_url, "Recipe source URL")
        # Freeze normalized copies so caller-owned lists cannot change a recipe.
        object.__setattr__(
            self, "ingredients", tuple(normalize_ingredient_name(item) for item in ingredients)
        )
        object.__setattr__(self, "instructions", instructions)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Recipe":
        value = _record(value, ("name", "ingredients", "instructions"), "Recipe")
        for field in ("ingredients", "instructions"):
            if not isinstance(value[field], list):
                raise ValueError(f"Recipe {field} must be an array")
        source_url = value.get("source_url")
        if source_url is not None:
            source_url = _string(source_url, "Recipe source URL")
        return cls(
            name=_string(value["name"], "Recipe name"),
            ingredients=_strings(value["ingredients"], "Recipe ingredients"),
            instructions=_strings(value["instructions"], "Recipe instructions"),
            source_url=source_url,
        )
