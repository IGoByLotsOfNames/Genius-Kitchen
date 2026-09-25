import unittest

from genius_kitchen.models import Recipe
from genius_kitchen.recipes import load_bundled_recipes, match_recipes


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


if __name__ == "__main__":
    unittest.main()
