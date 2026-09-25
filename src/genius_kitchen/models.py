from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Ingredient:
    name: str
    quantity: float
    unit: str
    expires_on: date
    category: str = "Other"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Ingredient name cannot be empty")
        if self.quantity <= 0:
            raise ValueError("Quantity must be positive")

    def days_until_expiry(self, today: date | None = None) -> int:
        return (self.expires_on - (today or date.today())).days

    def to_dict(self) -> dict[str, str | float]:
        value = asdict(self)
        value["expires_on"] = self.expires_on.isoformat()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Ingredient":
        return cls(
            name=str(value["name"]),
            quantity=float(value["quantity"]),
            unit=str(value["unit"]),
            expires_on=date.fromisoformat(str(value["expires_on"])),
            category=str(value.get("category", "Other")),
        )


@dataclass(frozen=True, slots=True)
class Recipe:
    name: str
    ingredients: tuple[str, ...]
    instructions: tuple[str, ...]
    source_url: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Recipe":
        return cls(
            name=str(value["name"]),
            ingredients=tuple(str(item).casefold() for item in value["ingredients"]),
            instructions=tuple(str(step) for step in value["instructions"]),
            source_url=str(value["source_url"]) if value.get("source_url") else None,
        )

