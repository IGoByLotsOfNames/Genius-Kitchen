import unittest
from datetime import date, timedelta

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

    def test_expiry_window_includes_today_and_its_last_day_only(self):
        inventory = Inventory(
            [
                Ingredient("Yesterday", 1, "item", self.today - timedelta(days=1)),
                Ingredient("Today", 1, "item", self.today),
                Ingredient("Last day", 1, "item", self.today + timedelta(days=3)),
                Ingredient("Beyond", 1, "item", self.today + timedelta(days=4)),
            ]
        )
        self.assertEqual(
            [item.name for item in inventory.expiring_within(0, self.today)], ["Today"]
        )
        self.assertEqual(
            [item.name for item in inventory.expiring_within(3, self.today)], ["Today", "Last day"]
        )
        self.assertEqual([item.name for item in inventory.expired(self.today)], ["Yesterday"])
        self.assertEqual(inventory.available_names(self.today), {"today", "last day", "beyond"})

    def test_expiry_calculation_handles_leap_day_and_year_boundaries(self):
        cases = (
            (date(2028, 2, 28), date(2028, 3, 1), 2),
            (date(2027, 2, 28), date(2027, 3, 1), 1),
            (date(2028, 12, 31), date(2029, 1, 1), 1),
        )
        for today, expiry, distance in cases:
            with self.subTest(today=today, expiry=expiry):
                item = Ingredient("Milk", 1, "litre", expiry)
                inventory = Inventory([item])
                self.assertEqual(item.days_until_expiry(today), distance)
                self.assertEqual(inventory.expiring_within(distance - 1, today), ())
                self.assertEqual(inventory.expiring_within(distance, today), (item,))
                self.assertEqual(inventory.expired(expiry), ())
                self.assertEqual(inventory.expired(expiry + timedelta(days=1)), (item,))

    def test_negative_expiry_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            self.inventory.expiring_within(-1, self.today)

    def test_inventory_copies_input_and_returns_an_immutable_sorted_snapshot(self):
        later = Ingredient("Later", 1, "item", self.today + timedelta(days=2))
        earlier = Ingredient("Earlier", 1, "item", self.today)
        source = [later, earlier]
        inventory = Inventory(source)
        source.clear()
        snapshot = inventory.ingredients
        self.assertIsInstance(snapshot, tuple)
        self.assertEqual(snapshot, (earlier, later))
        inventory.remove(earlier)
        self.assertEqual(snapshot, (earlier, later))
        self.assertEqual(inventory.ingredients, (later,))

    def test_add_remove_and_empty_inventory_queries(self):
        inventory = Inventory()
        self.assertEqual(inventory.ingredients, ())
        self.assertEqual(inventory.expiring_within(3, self.today), ())
        self.assertEqual(inventory.expired(self.today), ())
        self.assertEqual(inventory.available_names(self.today), set())
        item = Ingredient(" Milk ", 1, "litre", self.today)
        inventory.add(item)
        self.assertEqual(inventory.available_names(self.today), {"milk"})
        inventory.remove(item)
        self.assertEqual(inventory.ingredients, ())


if __name__ == "__main__":
    unittest.main()
