"""Real Tk integration tests, with synthetic inventory and non-blocking dialogs.

GK_REQUIRE_GUI=1 makes an unavailable Tk/display an error (required in CI).
Without it, headless developers get an explicit skip rather than an import error.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

try:
    import tkinter as tk
except ImportError as exc:
    tk = None
    TK_IMPORT_ERROR = str(exc)

if tk is not None:
    import genius_kitchen.app as ui

from genius_kitchen.inventory import Inventory
from genius_kitchen.models import Ingredient, Recipe
from genius_kitchen.storage import JSONInventoryStore

DAY = date(2026, 10, 2)


class TkCase(unittest.TestCase):
    def setUp(self):
        if tk is None:
            self.unavailable_gui(f"Tkinter could not be imported: {TK_IMPORT_ERROR}")
        self.callback_errors = []
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.unavailable_gui(f"Tk could not initialize a display/runtime: {exc}")
        self.root_destroyed = False
        self.original_destroy = self.root.destroy
        self.root.destroy = self.record_root_destruction
        self.addCleanup(self.destroy_root)
        self.root.withdraw()
        self.root.report_callback_exception = self.record_callback_error
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.directory = Path(self.scratch.name)
        self.store = JSONInventoryStore(self.directory / "inventory.json")
        self.errors = self.enterContext(patch.object(ui.messagebox, "showerror"))

    def unavailable_gui(self, message):
        if os.environ.get("GK_REQUIRE_GUI") == "1":
            raise RuntimeError(f"GUI tests are required: {message}")
        self.skipTest(f"GUI unavailable; set GK_REQUIRE_GUI=1 to require it: {message}")

    def destroy_root(self):
        if not self.root_destroyed:
            self.root.destroy()
        self.assertEqual(self.callback_errors, [], "Tk callback raised an exception")

    def record_root_destruction(self):
        # Startup failures close their root themselves. Track successful closure
        # so cleanup never closes it twice or suppresses unrelated Tcl errors.
        self.original_destroy()
        self.root_destroyed = True

    def record_callback_error(self, exception_type, exception, traceback):
        self.callback_errors.append(f"{exception_type.__name__}: {exception}")


class AppTests(TkCase):
    def setUp(self):
        super().setUp()
        self.clock_day = DAY
        self.clock_calls = 0
        self.store.save(
            Inventory(
                [
                    Ingredient("Milk", 1, "litre", DAY),
                    Ingredient("Rice", 1, "kg", DAY + timedelta(days=5)),
                ]
            )
        )
        self.app = ui.GeniusKitchenApp(self.root, self.store, today=self.today)
        self.root.update_idletasks()

    def today(self):
        self.clock_calls += 1
        return self.clock_day

    def select(self, name):
        row = next(row for row, item in self.app._rows.items() if item.name == name)
        self.app.tree.selection_set(row)
        return self.app._rows[row]

    def snapshot(self):
        return (
            self.app.inventory.ingredients,
            tuple((row, self.app.tree.item(row, "values")) for row in self.app.tree.get_children()),
            self.app.tree.selection(),
            self.app.recipe_text.get("1.0", "end"),
            self.store.path.read_bytes(),
        )

    def dispatch_date_check(self):
        # Deliver the scheduled callback via Tcl's real event loop, without
        # sleeping for a second or leaving the original callback pending.
        self.app.after_cancel(self.app._date_refresh_id)
        self.app._date_refresh_id = self.app.after(0, self.app._check_date)
        self.root.update()

    def test_failed_remove_preserves_state_and_retry_removes_only_selection(self):
        self.select("Milk")
        before = self.snapshot()
        with patch.object(self.store, "save", side_effect=OSError("disk full")):
            self.app._remove()
        self.assertEqual(self.snapshot(), before)
        self.errors.assert_called_once()
        self.app._remove()
        self.assertEqual([item.name for item in self.store.load().ingredients], ["Rice"])

    def test_failed_add_preserves_form_selection_and_all_states(self):
        self.select("Rice")
        self.app.name_var.set("Egg")
        self.app.expiry_var.set("2031-12-31")
        before = self.snapshot()
        for failure in (OSError("denied write"), ValueError("invalid serialization")):
            with self.subTest(failure=type(failure).__name__):
                with patch.object(self.store, "save", side_effect=failure):
                    self.app._add()
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.app.name_var.get(), "Egg")
                self.assertEqual(self.app.expiry_var.get(), "2031-12-31")
        self.assertEqual(self.errors.call_count, 2)

    def test_successful_add_reorders_rows_and_preserves_selected_object(self):
        selected = self.select("Rice")
        self.app.name_var.set("Egg")
        self.app.expiry_var.set((DAY - timedelta(days=1)).isoformat())
        self.app._add()
        self.assertIs(self.app._rows[self.app.tree.selection()[0]], selected)
        self.assertEqual(self.app.name_var.get(), "")
        self.assertEqual(
            [item.name for item in self.store.load().ingredients], ["Egg", "Milk", "Rice"]
        )
        self.errors.assert_not_called()

    def test_equal_items_remove_selected_identity_only(self):
        first = Ingredient("Milk", 1, "litre", DAY)
        second = Ingredient("Milk", 1, "litre", DAY)
        self.app.inventory = Inventory([first, second])
        self.app._refresh_views()
        self.app.tree.selection_set(self.app.tree.get_children()[1])
        self.app._refresh_views()
        self.assertIs(self.app._rows[self.app.tree.selection()[0]], second)
        self.app._remove()
        self.assertEqual(len(self.app.inventory.ingredients), 1)
        self.assertIs(self.app.inventory.ingredients[0], first)
        self.assertEqual(self.app.tree.selection(), ())

    def test_repeated_object_reference_removes_one_occurrence(self):
        item = Ingredient("Milk", 1, "litre", DAY)
        self.app.inventory = Inventory([item, item])
        self.app._refresh_views()
        self.app.tree.selection_set(self.app.tree.get_children()[1])
        self.app._remove()
        self.assertEqual(len(self.app.inventory.ingredients), 1)

    def test_remove_without_selection_does_not_save(self):
        before = self.snapshot()
        with patch.object(self.store, "save") as save:
            self.app._remove()
        save.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_stale_selection_refreshes_without_removing_another_item(self):
        self.select("Milk")
        rice = self.app.inventory.ingredients[1]
        self.app.inventory = Inventory([rice])
        with patch.object(self.store, "save") as save:
            self.app._remove()
        save.assert_not_called()
        self.assertEqual(self.app.inventory.ingredients, (rice,))
        self.assertEqual(self.app.tree.selection(), ())

    def test_invalid_form_input_does_not_save(self):
        invalid = (
            ("quantity_var", "nan"),
            ("quantity_var", "lots"),
            ("expiry_var", "2026-02-30"),
            ("name_var", "  "),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                self.app.name_var.set("Egg")
                self.app.quantity_var.set("1")
                self.app.expiry_var.set(DAY.isoformat())
                getattr(self.app, field).set(value)
                before = self.snapshot()
                with patch.object(self.store, "save") as save:
                    self.app._add()
                save.assert_not_called()
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.errors.call_count, len(invalid))

    def test_refresh_samples_date_once_without_overwriting_form(self):
        self.app.expiry_var.set("2031-12-31")
        self.clock_calls = 0
        self.app._refresh_views()
        self.assertEqual(self.clock_calls, 1)
        self.assertEqual(self.app.expiry_var.get(), "2031-12-31")

    def test_date_change_refreshes_both_views_forward_and_backward(self):
        self.app.recipes = (Recipe("Milk recipe", ("milk",), ("Serve",)),)
        selected = self.select("Rice")
        self.app.name_var.set("Unfinished entry")
        for delta, status, coverage in ((1, "Expired", "0%"), (0, "Expiring soon", "100%")):
            with self.subTest(delta=delta):
                self.clock_day = DAY + timedelta(days=delta)
                self.dispatch_date_check()
                row = next(row for row, item in self.app._rows.items() if item.name == "Milk")
                self.assertEqual(self.app.tree.item(row, "values")[-1], status)
                self.assertIn(
                    f"— {coverage} ingredients available", self.app.recipe_text.get("1.0", "end")
                )
                self.assertEqual(self.app._display_date, self.clock_day)
                self.assertIs(self.app._rows[self.app.tree.selection()[0]], selected)
                self.assertEqual(self.app.name_var.get(), "Unfinished entry")
                self.assertEqual(
                    tuple(self.root.tk.call("after", "info")), (self.app._date_refresh_id,)
                )

    def test_same_date_does_not_rebuild_views_and_keeps_one_successor(self):
        before = self.snapshot()
        with patch.object(self.app, "_refresh_views", wraps=self.app._refresh_views) as refresh:
            self.dispatch_date_check()
        refresh.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(tuple(self.root.tk.call("after", "info")), (self.app._date_refresh_id,))

    def test_manual_refresh_keeps_timer_and_destroy_cancels_it(self):
        job = self.app._date_refresh_id
        for _ in range(4):
            self.app._refresh_views()
        self.assertEqual(self.app._date_refresh_id, job)
        self.assertIn(job, self.root.tk.call("after", "info"))
        self.app.destroy()
        self.assertNotIn(job, self.root.tk.call("after", "info"))


class StartupTests(TkCase):
    def test_invalid_inventory_reports_error_without_reset(self):
        self.store.path.write_bytes(b"{")
        self.check_failure(["--data-dir", str(self.directory)])
        self.assertEqual(self.store.path.read_bytes(), b"{")

    def test_missing_recipe_reports_error_without_creating_inventory(self):
        self.check_failure(
            [
                "--data-dir",
                str(self.directory),
                "--recipes",
                str(self.directory / "missing.json"),
            ]
        )
        self.assertFalse(self.store.path.exists())

    def check_failure(self, args):
        # A real modal dialog pumps idle events; emulate that before root.destroy().
        self.errors.side_effect = lambda *args, **kwargs: kwargs["parent"].update_idletasks()
        with (
            patch.object(sys, "argv", ["genius-kitchen", *args]),
            patch.object(ui.tk, "Tk", return_value=self.root),
        ):
            with self.assertRaises(SystemExit) as stopped:
                ui.main()
        self.assertEqual(stopped.exception.code, 1)
        self.errors.assert_called_once()
        self.assertIn(self.directory.name, self.errors.call_args.args[1])

    def test_successful_startup_uses_explicit_data_and_custom_recipes(self):
        recipes = self.directory / "recipes.json"
        recipes.write_text(
            '[{"name":"Toast","ingredients":["bread"],"instructions":["Toast it"]}]',
            encoding="utf-8",
        )
        args = ["genius-kitchen", "--data-dir", str(self.directory), "--recipes", str(recipes)]
        with (
            patch.object(sys, "argv", args),
            patch.object(ui.tk, "Tk", return_value=self.root),
            patch.object(self.root, "deiconify") as show,
            patch.object(self.root, "mainloop") as loop,
        ):
            ui.main()
        self.root.update_idletasks()
        show.assert_called_once()
        loop.assert_called_once()
        self.errors.assert_not_called()
        app = next(
            child for child in self.root.winfo_children() if isinstance(child, ui.GeniusKitchenApp)
        )
        self.assertEqual(app.store.path, self.store.path)
        self.assertEqual([recipe.name for recipe in app.recipes], ["Toast"])
        self.assertFalse(self.store.path.exists())


if __name__ == "__main__":
    unittest.main()
