# demo.py
"""Run a fresh Genius Kitchen demo: python demo.py (Python 3.11+ with Tk).

--check validates sample data without a GUI or inventory writes.
--smoke-test exercises the real GUI in a hidden window and exits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
if sys.version_info < (3, 11):
    raise SystemExit("The Genius Kitchen demo requires Python 3.11 or newer.")
# Direct launches run checkout source without pip; importing for tests must not
# change which installed application package the surrounding process uses.
if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(PROJECT / "src"))
from genius_kitchen.inventory import Inventory  # noqa: E402
from genius_kitchen.models import Ingredient  # noqa: E402
from genius_kitchen.recipes import load_bundled_recipes, match_recipes  # noqa: E402
from genius_kitchen.storage import JSONInventoryStore  # noqa: E402

EXPECTED_MATCHES = (
    ("Tomato Omelette", 100, ()),
    ("Vegetable Fried Rice", 100, ()),
    ("Banana Oat Pancakes", 75, ("milk",)),
    ("Simple Shakshuka", 50, ("onion", "garlic")),
    ("Chicken and Vegetable Soup", 25, ("chicken", "onion", "potato")),
    ("Garlic Butter Pasta", 0, ("pasta", "garlic", "butter", "parmesan")),
)


def sample_inventory(reference: date) -> Inventory:
    rows = json.loads((PROJECT / "demo/pantry.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Demo pantry must be a JSON array")
    items = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each demo pantry entry must be an object")
        if type(row.get("expires_in_days")) is not int:
            raise ValueError("Demo expiry offsets must be integer days")
        items.append(
            Ingredient(
                name=row["name"],
                quantity=row["quantity"],
                unit=row["unit"],
                category=row["category"],
                expires_on=reference + timedelta(days=row["expires_in_days"]),
            )
        )
    return Inventory(items)


def verify_sample(inventory: Inventory, reference: date) -> None:
    matches = match_recipes(inventory.available_names(reference), load_bundled_recipes())
    actual = tuple(
        (match.recipe.name, round(match.coverage * 100), match.missing) for match in matches
    )
    if actual != EXPECTED_MATCHES:
        raise ValueError("Demo recipe results changed; update and verify the expected walkthrough")
    if len(inventory.ingredients) != 9 or [item.name for item in inventory.expired(reference)] != [
        "Milk"
    ]:
        raise ValueError("Demo should have nine ingredients with only the milk expired")


def print_expected(reference: date) -> None:
    print(f"Genius Kitchen demo - sample dates relative to {reference.isoformat()}")
    print("Inventory: 9 ingredients; Milk is expired, Egg expires today.")
    print("Recipe matches:")
    for name, percent, missing in EXPECTED_MATCHES:
        print(f"  {name}: {percent}% | Missing: {', '.join(missing) or 'nothing'}")
    print("Try: add Milk, quantity 1, unit litre, category Dairy, keeping today's expiry.")
    print("Banana Oat Pancakes should become 100%; remove the new milk to return to 75%.")


def configure_tk_runtime(tk) -> None:
    """Use matching Tcl scripts beside a portable Python, if supplied there."""
    bundled = Path(sys.base_prefix) / "tcl"
    for key, folder, marker in (
        ("TCL_LIBRARY", f"tcl{tk.TclVersion}", "init.tcl"),
        ("TK_LIBRARY", f"tk{tk.TkVersion}", "tk.tcl"),
    ):
        candidate = bundled / folder
        if key not in os.environ and (candidate / marker).is_file():
            os.environ[key] = str(candidate)


def new_demo_store(inventory: Inventory) -> JSONInventoryStore:
    parent = PROJECT / ".demo-runs"
    parent.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="demo-", dir=parent))
    store = JSONInventoryStore(directory / "inventory.json")
    store.save(inventory)
    return store


def invoke_button(widget, text: str) -> bool:
    for child in widget.winfo_children():
        if child.winfo_class() == "TButton" and child.cget("text") == text:
            child.invoke()
            return True
        if invoke_button(child, text):
            return True
    return False


def smoke_check(app, reference: date) -> None:
    """Exercise the walkthrough using real widgets and persistence, then restore it."""
    if len(app.tree.get_children()) != 9:
        raise RuntimeError("Demo GUI did not display all nine ingredients")
    milk_row = next(row for row, item in app._rows.items() if item.name == "Milk")
    if app.tree.item(milk_row, "values")[-1] != "Expired":
        raise RuntimeError("Expired milk was not marked in the GUI")
    for name, percent, _ in EXPECTED_MATCHES:
        if f"{name} — {percent}% ingredients available" not in app.recipe_text.get("1.0", "end"):
            raise RuntimeError(f"Unexpected recipe text for {name}")
    app.name_var.set("Milk")
    app.quantity_var.set("1")
    app.unit_var.set("litre")
    app.category_var.set("Dairy")
    app.expiry_var.set(reference.isoformat())
    if not invoke_button(app, "Add ingredient"):
        raise RuntimeError("Add ingredient button not found")
    if len(app.store.load().ingredients) != 10:
        raise RuntimeError("Adding demo milk did not persist")
    if "Banana Oat Pancakes — 100%" not in app.recipe_text.get("1.0", "end"):
        raise RuntimeError("Fresh milk did not update recipe matching")
    row = next(
        row
        for row, item in app._rows.items()
        if item.name == "Milk" and item.expires_on == reference
    )
    app.tree.selection_set(row)
    if not invoke_button(app, "Remove selected"):
        raise RuntimeError("Remove selected button not found")
    verify_sample(app.store.load(), reference)
    if "Banana Oat Pancakes — 75%" not in app.recipe_text.get("1.0", "end"):
        raise RuntimeError("Removing fresh milk did not restore recipe matching")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    reference = date.today()
    try:
        inventory = sample_inventory(reference)
        verify_sample(inventory, reference)
    except (OSError, ValueError, KeyError, OverflowError) as exc:
        print(f"Cannot load the demo sample: {exc}", file=sys.stderr)
        return 1
    print_expected(reference)
    if args.check:
        print("Sample check passed. No window opened or inventory files written.")
        return 0
    try:
        import tkinter as tk

        from genius_kitchen.app import GeniusKitchenApp
    except ImportError as exc:
        print(
            f"Tkinter is required; use Python 3.11+ with Tcl/Tk installed. {exc}", file=sys.stderr
        )
        return 1
    configure_tk_runtime(tk)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(
            f"Cannot open the demo: {exc}\nCheck Tcl/Tk and a graphical display. No demo inventory was written.",
            file=sys.stderr,
        )
        return 1
    root.withdraw()
    root.protocol("WM_DELETE_WINDOW", root.quit)
    failures = []
    dialog_patch = None
    if args.smoke_test:
        from unittest.mock import patch

        dialog_patch = patch(
            "genius_kitchen.app.messagebox.showerror",
            side_effect=RuntimeError("Unexpected error dialog during GUI smoke check"),
        )
        dialog_patch.start()

    def callback_error(kind, error, traceback):
        failures.append(f"{kind.__name__}: {error}")
        root.quit()

    root.report_callback_exception = callback_error
    try:
        store = new_demo_store(inventory)
        app = GeniusKitchenApp(root, store, today=(lambda: reference) if args.smoke_test else None)
        root.title("Genius Kitchen - Demo")
        root.update_idletasks()
        print(f"Demo inventory saved to: {store.path}", flush=True)
        if args.smoke_test:
            # Drain the real event loop once; all assertions run on the Tk thread.
            def check_and_quit():
                smoke_check(app, reference)
                root.quit()

            root.after_idle(check_and_quit)
        else:
            root.deiconify()
        root.mainloop()
    except (OSError, ValueError, tk.TclError) as exc:
        failures.append(str(exc))
    finally:
        # The window manager's close action must quit before this single destroy.
        root.destroy()
        if dialog_patch is not None:
            dialog_patch.stop()
    if failures:
        print("Demo failed: " + "; ".join(failures), file=sys.stderr)
        return 1
    if args.smoke_test:
        print("GUI smoke check passed: initial results, add/remove, and persisted state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
