from datetime import date
import unittest

from genius_kitchen.inventory import Inventory
from genius_kitchen.models import Ingredient


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 9, 25)
        self.inventory = Inventory(
            [
                Ingredient("Milk", 1, "carton", date(2026, 9, 27), "Dairy"),
                Ingredient("Rice", 2, "kg", date(2027, 1, 1), "Pantry"),
                Ingredient("Spinach", 1, "bag", date(2026, 9, 24), "Vegetable"),
            ]
        )

    def test_expiring_items_are_selected_without_expired_items(self) -> None:
        self.assertEqual(
            [item.name for item in self.inventory.expiring_within(3, self.today)],
            ["Milk"],
        )

    def test_expired_items_are_reported(self) -> None:
        self.assertEqual([item.name for item in self.inventory.expired(self.today)], ["Spinach"])

    def test_available_names_exclude_expired_items(self) -> None:
        self.assertEqual(self.inventory.available_names(self.today), {"milk", "rice"})


if __name__ == "__main__":
    unittest.main()

