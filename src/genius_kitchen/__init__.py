"""Genius Kitchen desktop application."""

from .inventory import Inventory
from .models import Ingredient, Recipe

__all__ = ["Ingredient", "Inventory", "Recipe"]
__version__ = "2.0.0"
