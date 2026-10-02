import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime

from genius_kitchen.models import Ingredient, Recipe, normalize_ingredient_name


class IngredientTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2028, 2, 29)
        self.record = {
            "name": "Milk",
            "quantity": 1.5,
            "unit": "litre",
            "expires_on": self.day.isoformat(),
            "category": "Dairy",
        }

    def test_positive_integer_and_fractional_quantities_are_supported(self):
        for quantity in (1, 0.25):
            with self.subTest(quantity=quantity):
                item = Ingredient("Milk", quantity, "litre", self.day)
                self.assertEqual(item.quantity, quantity)

    def test_invalid_quantities_are_rejected_by_both_entry_points(self):
        quantities = (
            float("nan"),
            float("inf"),
            -float("inf"),
            0,
            -1,
            True,
            False,
            "2",
            None,
            [],
            10**400,
        )
        for quantity in quantities:
            with self.subTest(quantity=repr(quantity)):
                with self.assertRaisesRegex(ValueError, "Quantity"):
                    Ingredient("Milk", quantity, "litre", self.day)
                with self.assertRaisesRegex(ValueError, "Quantity"):
                    Ingredient.from_dict({**self.record, "quantity": quantity})

    def test_display_name_is_trimmed_and_ingredient_is_frozen(self):
        item = Ingredient(" Milk ", 1, "litre", self.day)
        self.assertEqual(item.name, "Milk")
        with self.assertRaises(FrozenInstanceError):
            item.quantity = 2

    def test_invalid_direct_fields_are_rejected(self):
        valid = {
            "name": "Milk",
            "quantity": 1,
            "unit": "litre",
            "expires_on": self.day,
            "category": "Dairy",
        }
        invalid = (
            ("name", " \t"),
            ("name", None),
            ("unit", []),
            ("category", None),
            ("expires_on", "2028-02-29"),
            ("expires_on", datetime(2028, 2, 29, 12)),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                Ingredient(**{**valid, field: value})

    def test_record_requires_an_object_and_all_required_fields(self):
        for value in (None, [], "Milk", 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "object"):
                Ingredient.from_dict(value)
        for field in ("name", "quantity", "unit", "expires_on"):
            incomplete = {key: value for key, value in self.record.items() if key != field}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                Ingredient.from_dict(incomplete)

    def test_record_rejects_wrong_field_types_and_invalid_dates(self):
        invalid = (
            ("name", None),
            ("unit", {}),
            ("category", None),
            ("expires_on", 20280229),
            ("expires_on", "2027-02-29"),
            ("expires_on", "not a date"),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                Ingredient.from_dict({**self.record, field: value})

    def test_dictionary_roundtrip_and_optional_category(self):
        item = Ingredient.from_dict(self.record)
        self.assertEqual(item.to_dict(), self.record)
        self.assertEqual(Ingredient.from_dict(item.to_dict()), item)
        without_category = {key: value for key, value in self.record.items() if key != "category"}
        self.assertEqual(Ingredient.from_dict(without_category).category, "Other")

    def test_identity_normalization_uses_casefold_and_whitespace_trimming(self):
        self.assertEqual(normalize_ingredient_name("  MiLK\t"), "milk")
        self.assertEqual(normalize_ingredient_name("Straße"), "strasse")
        for value in ("", " \n", None, 3):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_ingredient_name(value)


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "name": "Egg meal",
            "ingredients": [" Egg ", "RICE"],
            "instructions": ["Cook", "Serve"],
            "source_url": "https://example.com/recipe",
        }

    def test_direct_and_loaded_recipes_normalize_the_same_way(self):
        direct = Recipe("Egg meal", (" Egg ", "RICE"), ("Cook", "Serve"), self.record["source_url"])
        loaded = Recipe.from_dict(self.record)
        self.assertEqual(direct, loaded)
        self.assertEqual(loaded.ingredients, ("egg", "rice"))
        self.assertEqual(loaded.source_url, self.record["source_url"])

    def test_recipe_copies_sequences_and_remains_frozen(self):
        ingredients, instructions = ["Egg"], ["Cook"]
        recipe = Recipe("Egg meal", ingredients, instructions)
        ingredients.append("Rice")
        instructions.append("Serve")
        self.assertEqual(recipe.ingredients, ("egg",))
        self.assertEqual(recipe.instructions, ("Cook",))
        with self.assertRaises(FrozenInstanceError):
            recipe.name = "Changed"

    def test_direct_recipe_rejects_invalid_fields_and_string_containers(self):
        valid = {"name": "Egg meal", "ingredients": ("egg",), "instructions": ("Cook",)}
        invalid = (
            ("name", None),
            ("ingredients", "egg"),
            ("instructions", "Cook"),
            ("ingredients", [None]),
            ("ingredients", [" "]),
            ("instructions", [3]),
            ("source_url", False),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                Recipe(**{**valid, field: value})

    def test_recipe_record_requires_object_fields_and_json_arrays(self):
        for value in (None, [], "Egg meal"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "object"):
                Recipe.from_dict(value)
        for field in ("name", "ingredients", "instructions"):
            incomplete = {key: value for key, value in self.record.items() if key != field}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                Recipe.from_dict(incomplete)
        for field in ("ingredients", "instructions"):
            for value in ("egg", ("egg",), None, {}):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaisesRegex(ValueError, "array"),
                ):
                    Recipe.from_dict({**self.record, field: value})

    def test_recipe_record_rejects_invalid_members_and_optional_url_types(self):
        for field, value in (
            ("ingredients", [None]),
            ("instructions", [3]),
            ("name", None),
            ("source_url", 4),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                Recipe.from_dict({**self.record, field: value})
        without_url = {key: value for key, value in self.record.items() if key != "source_url"}
        self.assertIsNone(Recipe.from_dict(without_url).source_url)


if __name__ == "__main__":
    unittest.main()
