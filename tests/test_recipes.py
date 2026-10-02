import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from genius_kitchen.models import Recipe
from genius_kitchen.recipes import load_bundled_recipes, load_recipes, match_recipes


class RecipeMatchingTests(unittest.TestCase):
    def test_bundled_recipe_data_is_available_after_installation(self) -> None:
        recipes = load_bundled_recipes()
        self.assertGreater(len(recipes), 0)

    def test_best_coverage_is_ranked_first(self) -> None:
        recipes = (
            Recipe("Complete", ("egg", "rice"), ("Cook",)),
            Recipe("Partial", ("egg", "rice", "onion"), ("Cook",)),
        )
        matches = match_recipes({"egg", "rice"}, recipes)
        self.assertEqual(matches[0].recipe.name, "Complete")
        self.assertEqual(matches[0].coverage, 1.0)

    def test_matching_normalizes_pantries_and_preserves_recipe_ingredient_order(self):
        recipe = Recipe("Meal", (" Rice ", "EGG", "Onion"), ("Cook",))
        match = match_recipes({" egg ", "rIcE"}, (recipe,))[0]
        self.assertEqual(match.available, ("rice", "egg"))
        self.assertEqual(match.missing, ("onion",))
        self.assertAlmostEqual(match.coverage, 2 / 3)

    def test_equal_coverage_prefers_fewer_missing_ingredients_then_name(self):
        recipes = (
            Recipe("Zulu", ("egg", "onion"), ("Cook",)),
            Recipe("More missing", ("egg", "rice", "onion", "carrot"), ("Cook",)),
            Recipe("Alpha", ("rice", "carrot"), ("Cook",)),
        )
        matches = match_recipes({"egg", "rice"}, recipes)
        self.assertEqual(
            [match.recipe.name for match in matches], ["Alpha", "Zulu", "More missing"]
        )
        self.assertEqual([match.coverage for match in matches], [0.5, 0.5, 0.5])

    def test_limit_is_applied_after_ranking(self):
        recipes = (
            Recipe("Partial", ("egg", "rice"), ("Cook",)),
            Recipe("Complete", ("egg",), ("Cook",)),
        )
        matches = match_recipes({"egg"}, recipes, limit=1)
        self.assertEqual([match.recipe.name for match in matches], ["Complete"])

    def test_empty_pantry_reports_all_ingredients_missing(self):
        recipe = Recipe("Meal", ("egg", "rice"), ("Cook",))
        match = match_recipes((), (recipe,))[0]
        self.assertEqual(match.available, ())
        self.assertEqual(match.missing, recipe.ingredients)
        self.assertEqual(match.coverage, 0)


class RecipeFileTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / "recipes.json"
        self.record = {"name": "Egg meal", "ingredients": [" Egg "], "instructions": ["Cook"]}

    def test_custom_recipe_file_loads_validated_recipes(self):
        self.path.write_text(json.dumps([self.record]), encoding="utf-8")
        self.assertEqual(load_recipes(self.path), (Recipe("Egg meal", ("egg",), ("Cook",)),))

    def test_malformed_recipe_file_reports_path_and_preserves_bytes(self):
        for content in (b"{", b"null", b"{}", b"[{}]", b"[3]", b"\xff"):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with self.assertRaisesRegex(ValueError, "recipes.json"):
                    load_recipes(self.path)
                self.assertEqual(self.path.read_bytes(), content)

    def test_invalid_record_reports_item_and_field(self):
        self.path.write_text(
            json.dumps([self.record, {**self.record, "ingredients": "egg"}]), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "recipes.json, item 2: Recipe ingredients"):
            load_recipes(self.path)

    def test_missing_custom_recipe_file_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            load_recipes(self.path)

    def test_recipe_read_permission_error_propagates(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("denied read")):
            with self.assertRaises(PermissionError):
                load_recipes(self.path)


if __name__ == "__main__":
    unittest.main()
