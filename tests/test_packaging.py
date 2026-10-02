"""Check the installed package contract; CI requires non-editable installation."""

import os
import unittest
from importlib.metadata import distribution
from pathlib import Path

import genius_kitchen
from genius_kitchen.recipes import load_bundled_recipes


class PackagingTests(unittest.TestCase):
    def test_installed_metadata_exposes_console_entry_point(self):
        package = distribution("genius-kitchen")
        entries = {
            entry.name: entry.value
            for entry in package.entry_points
            if entry.group == "console_scripts"
        }
        self.assertEqual(entries["genius-kitchen"], "genius_kitchen.app:main")

    def test_bundled_recipes_are_available_from_installed_package(self):
        recipes = load_bundled_recipes()
        self.assertGreater(len(recipes), 0)
        self.assertTrue(all(recipe.name and recipe.ingredients for recipe in recipes))

    def test_import_origin_matches_installation_mode(self):
        origin = Path(genius_kitchen.__file__).resolve()
        self.assertTrue(origin.is_file())
        if os.environ.get("GK_EXPECT_INSTALLED") == "1":
            checkout_source = Path(__file__).resolve().parents[1] / "src"
            self.assertFalse(
                origin.is_relative_to(checkout_source), f"Expected installed package, got {origin}"
            )


if __name__ == "__main__":
    unittest.main()
