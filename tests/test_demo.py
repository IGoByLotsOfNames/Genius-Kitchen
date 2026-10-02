# tests/test_demo.py
"""Sample reproducibility and demo isolation; real GUI smoke checks run separately."""

import builtins
import importlib
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import demo
from genius_kitchen.models import Ingredient


class DemoSampleTests(unittest.TestCase):
    def test_importing_demo_does_not_change_application_import_paths(self):
        before = list(demo.sys.path)
        importlib.reload(demo)
        self.assertEqual(demo.sys.path, before)

    def test_sample_stays_correct_across_leap_days_and_year_boundaries(self):
        for reference in (
            date(2027, 2, 28),
            date(2028, 2, 28),
            date(2028, 2, 29),
            date(2028, 12, 31),
            date(2029, 1, 1),
        ):
            with self.subTest(reference=reference):
                inventory = demo.sample_inventory(reference)
                demo.verify_sample(inventory, reference)
                self.assertEqual(len(inventory.ingredients), 9)
                self.assertEqual([item.name for item in inventory.expired(reference)], ["Milk"])
                egg = next(item for item in inventory.ingredients if item.name == "Egg")
                self.assertEqual(egg.expires_on, reference)
                matches = demo.match_recipes(
                    inventory.available_names(reference), demo.load_bundled_recipes()
                )
                actual = tuple(
                    (item.recipe.name, round(item.coverage * 100), item.missing) for item in matches
                )
                self.assertEqual(actual, demo.EXPECTED_MATCHES)

    def test_fixture_rejects_boolean_and_fractional_expiry_offsets(self):
        row = {
            "name": "Milk",
            "quantity": 1,
            "unit": "litre",
            "category": "Dairy",
            "expires_in_days": -1,
        }
        for offset in (True, 0.5, "1", None):
            with self.subTest(offset=offset):
                content = json.dumps([{**row, "expires_in_days": offset}])
                with patch.object(Path, "read_text", return_value=content):
                    with self.assertRaisesRegex(ValueError, "integer days"):
                        demo.sample_inventory(date(2028, 2, 29))

        for content in ("null", "{}", "[null]", "[3]"):
            with (
                self.subTest(content=content),
                patch.object(Path, "read_text", return_value=content),
            ):
                with self.assertRaises(ValueError):
                    demo.sample_inventory(date(2028, 2, 29))

    def test_sample_verification_detects_changes_to_expired_records_and_matches(self):
        reference = date(2028, 2, 29)
        inventory = demo.sample_inventory(reference)
        expired_milk = next(item for item in inventory.ingredients if item.name == "Milk")
        inventory.remove(expired_milk)
        with self.assertRaisesRegex(ValueError, "nine ingredients"):
            demo.verify_sample(inventory, reference)
        inventory = demo.sample_inventory(reference)
        egg = next(item for item in inventory.ingredients if item.name == "Egg")
        inventory.remove(egg)
        with self.assertRaisesRegex(ValueError, "recipe results changed"):
            demo.verify_sample(inventory, reference)

    def test_check_mode_does_not_import_gui_or_write_inventory(self):
        real_import = builtins.__import__
        imported = []

        def guarded_import(name, *args, **kwargs):
            imported.append(name)
            if name == "tkinter" or name.startswith("tkinter.") or name == "genius_kitchen.app":
                raise AssertionError("--check must not import the GUI")
            return real_import(name, *args, **kwargs)

        output = io.StringIO()
        with (
            patch.object(builtins, "__import__", side_effect=guarded_import),
            patch.object(
                demo, "new_demo_store", side_effect=AssertionError("no demo writes")
            ) as create,
            patch.object(
                demo.JSONInventoryStore, "save", side_effect=AssertionError("no store writes")
            ) as save,
            patch.object(Path, "mkdir", side_effect=AssertionError("no new directories")) as mkdir,
            patch.object(Path, "write_text", side_effect=AssertionError("no text writes")) as write,
            patch("sys.stdout", output),
        ):
            self.assertEqual(demo.main(["--check"]), 0)
            create.assert_not_called()
            save.assert_not_called()
            mkdir.assert_not_called()
            write.assert_not_called()
        self.assertFalse(any(name.startswith("tkinter") for name in imported))
        self.assertIn(
            "Sample check passed. No window opened or inventory files written.", output.getvalue()
        )


class DemoIsolationTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.directory = Path(scratch.name)

    def test_each_launch_gets_fresh_inventory_without_changing_prior_or_personal_data(self):
        reference = date(2028, 2, 29)
        inventory = demo.sample_inventory(reference)
        personal = self.directory / ".genius-kitchen" / "inventory.json"
        personal.parent.mkdir()
        personal.write_bytes(b"personal inventory untouched")
        with (
            patch.object(demo, "PROJECT", self.directory),
            patch.object(
                Path, "home", side_effect=AssertionError("demo must not use personal home")
            ),
        ):
            first = demo.new_demo_store(inventory)
            edited = first.load()
            edited.add(Ingredient("User addition", 1, "item", reference))
            first.save(edited)
            first_bytes = first.path.read_bytes()
            second = demo.new_demo_store(inventory)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(first.path.parent.parent, self.directory / ".demo-runs")
        self.assertEqual(second.path.parent.parent, self.directory / ".demo-runs")
        self.assertEqual(first.path.read_bytes(), first_bytes)
        self.assertEqual(len(first.load().ingredients), 10)
        self.assertEqual(second.load().ingredients, inventory.ingredients)
        self.assertEqual(personal.read_bytes(), b"personal inventory untouched")

    def test_unwritable_demo_directory_fails_without_an_alternate_store(self):
        inventory = demo.sample_inventory(date(2028, 2, 29))
        with (
            patch.object(demo, "PROJECT", self.directory),
            patch.object(Path, "mkdir", side_effect=PermissionError("demo directory is read-only")),
            patch.object(demo.tempfile, "mkdtemp") as temporary,
            patch.object(demo.JSONInventoryStore, "save") as save,
            patch.object(Path, "home", side_effect=AssertionError("no personal fallback")),
        ):
            with self.assertRaisesRegex(PermissionError, "read-only"):
                demo.new_demo_store(inventory)
            temporary.assert_not_called()
            save.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_existing_tcl_and_tk_environment_settings_are_preserved(self):
        tcl = self.directory / "tcl" / "tcl8.6"
        tk = self.directory / "tcl" / "tk8.6"
        tcl.mkdir(parents=True)
        tk.mkdir()
        (tcl / "init.tcl").write_text("fixture", encoding="utf-8")
        (tk / "tk.tcl").write_text("fixture", encoding="utf-8")
        for existing in ("custom-location", ""):
            with self.subTest(existing=existing):
                with (
                    patch.object(demo.sys, "base_prefix", str(self.directory)),
                    patch.dict(
                        demo.os.environ,
                        {"TCL_LIBRARY": existing, "TK_LIBRARY": existing},
                        clear=True,
                    ),
                ):
                    demo.configure_tk_runtime(SimpleNamespace(TclVersion=8.6, TkVersion=8.6))
                    self.assertEqual(demo.os.environ["TCL_LIBRARY"], existing)
                    self.assertEqual(demo.os.environ["TK_LIBRARY"], existing)

    def test_tcl_and_tk_are_discovered_only_when_the_matching_marker_exists(self):
        tcl = self.directory / "tcl" / "tcl8.6"
        tk = self.directory / "tcl" / "tk8.6"
        tcl.mkdir(parents=True)
        tk.mkdir()
        fake_tk = SimpleNamespace(TclVersion=8.6, TkVersion=8.6)
        with (
            patch.object(demo.sys, "base_prefix", str(self.directory)),
            patch.dict(demo.os.environ, {}, clear=True),
        ):
            demo.configure_tk_runtime(fake_tk)
            self.assertNotIn("TCL_LIBRARY", demo.os.environ)
            self.assertNotIn("TK_LIBRARY", demo.os.environ)
            (tcl / "init.tcl").write_text("fixture", encoding="utf-8")
            demo.configure_tk_runtime(fake_tk)
            self.assertEqual(demo.os.environ["TCL_LIBRARY"], str(tcl))
            self.assertNotIn("TK_LIBRARY", demo.os.environ)
            (tk / "tk.tcl").write_text("fixture", encoding="utf-8")
            demo.configure_tk_runtime(fake_tk)
            self.assertEqual(demo.os.environ["TK_LIBRARY"], str(tk))


if __name__ == "__main__":
    unittest.main()
