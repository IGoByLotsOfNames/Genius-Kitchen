from __future__ import annotations

import argparse
import tkinter as tk
from collections.abc import Callable
from datetime import date
from pathlib import Path
from tkinter import messagebox, ttk

from .inventory import Inventory
from .models import Ingredient
from .recipes import load_bundled_recipes, load_recipes, match_recipes
from .storage import JSONInventoryStore


class GeniusKitchenApp(ttk.Frame):
    def __init__(
        self,
        master: tk.Tk,
        store: JSONInventoryStore,
        recipes_path: Path | None = None,
        *,
        today: Callable[[], date] | None = None,
    ) -> None:
        super().__init__(master, padding=18)
        self._date_refresh_id: str | None = None
        self._today = today if today is not None else date.today
        self._display_date: date | None = None
        self._rows: dict[str, Ingredient] = {}
        self.store = store
        self.inventory = store.load()
        self.recipes = load_recipes(recipes_path) if recipes_path else load_bundled_recipes()
        self.grid(sticky="nsew")
        master.title("Genius Kitchen")
        master.geometry("900x610")
        master.minsize(900, 610)
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self._build()
        self._refresh_views()
        self._date_refresh_id = self.after(1000, self._check_date)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="Genius Kitchen", font=("Segoe UI", 24, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="Track ingredients, surface expiring food and find recipes from what you have.",
        ).grid(row=1, column=0, sticky="w", pady=(0, 14))

        notebook = ttk.Notebook(self)
        notebook.grid(row=2, column=0, sticky="nsew")
        inventory_tab = ttk.Frame(notebook, padding=12)
        recipe_tab = ttk.Frame(notebook, padding=12)
        notebook.add(inventory_tab, text="Inventory")
        notebook.add(recipe_tab, text="Recipe matches")

        inventory_tab.columnconfigure(0, weight=1)
        inventory_tab.rowconfigure(0, weight=1)
        columns = ("name", "quantity", "category", "expiry", "status")
        self.tree = ttk.Treeview(
            inventory_tab, columns=columns, show="headings", height=14, selectmode="browse"
        )
        for column, label, width in zip(
            columns,
            ("Ingredient", "Quantity", "Category", "Expiry", "Status"),
            (175, 115, 135, 125, 145),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=80)
        self.tree.grid(row=0, column=0, columnspan=5, sticky="nsew")

        self.name_var = tk.StringVar()
        self.quantity_var = tk.StringVar(value="1")
        self.unit_var = tk.StringVar(value="item")
        self.category_var = tk.StringVar(value="Other")
        self.expiry_var = tk.StringVar(value=self._today().isoformat())
        fields = (
            ("Name", self.name_var),
            ("Quantity", self.quantity_var),
            ("Unit", self.unit_var),
            ("Category", self.category_var),
            ("Expiry (YYYY-MM-DD)", self.expiry_var),
        )
        for column, (label, variable) in enumerate(fields):
            frame = ttk.Frame(inventory_tab)
            frame.grid(row=1, column=column, padx=4, pady=10, sticky="ew")
            ttk.Label(frame, text=label).pack(anchor="w")
            ttk.Entry(frame, textvariable=variable, width=18).pack(fill="x")
        ttk.Button(inventory_tab, text="Add ingredient", command=self._add).grid(
            row=2, column=0, sticky="w"
        )
        ttk.Button(inventory_tab, text="Remove selected", command=self._remove).grid(
            row=2, column=1, sticky="w"
        )

        recipe_tab.columnconfigure(0, weight=1)
        recipe_tab.rowconfigure(1, weight=1)
        ttk.Button(recipe_tab, text="Refresh matches", command=self._refresh_views).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.recipe_text = tk.Text(recipe_tab, wrap="word", font=("Segoe UI", 11), padx=10, pady=10)
        self.recipe_text.grid(row=1, column=0, sticky="nsew")

    def _add(self) -> None:
        try:
            item = Ingredient(
                name=self.name_var.get(),
                quantity=float(self.quantity_var.get()),
                unit=self.unit_var.get(),
                category=self.category_var.get(),
                expires_on=date.fromisoformat(self.expiry_var.get()),
            )
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Invalid ingredient", str(exc))
            return
        candidate = Inventory(self.inventory.ingredients)
        candidate.add(item)
        if self._save_candidate(candidate):
            self.name_var.set("")

    def _save_candidate(self, candidate: Inventory) -> bool:
        """Adopt the proposed state only after it has been saved successfully."""
        try:
            self.store.save(candidate)
        except (OSError, ValueError) as exc:
            messagebox.showerror(
                "Unable to save inventory",
                f"Could not save your change. Check the file location and try again.\n\n{exc}",
                parent=self.winfo_toplevel(),
            )
            return False
        self.inventory = candidate
        self._refresh_views()
        return True

    def _remove(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        selected_item = self._rows.get(selection[0])
        items = list(self.inventory.ingredients)
        for index, item in enumerate(items):
            if item is selected_item:
                del items[index]
                self._save_candidate(Inventory(items))
                return
        self._refresh_views()

    def _refresh_views(self, reference: date | None = None) -> None:
        reference = reference if reference is not None else self._today()
        self._refresh_inventory(reference)
        self._refresh_recipes(reference)
        self._display_date = reference

    def _refresh_inventory(self, reference: date) -> None:
        selection = self.tree.selection()
        selected_item = self._rows.get(selection[0]) if selection else None
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        restored_selection = False
        for item in self.inventory.ingredients:
            days = item.days_until_expiry(reference)
            status = "Expired" if days < 0 else ("Expiring soon" if days <= 3 else f"{days} days")
            row = self.tree.insert(
                "",
                "end",
                values=(
                    item.name,
                    f"{item.quantity:g} {item.unit}",
                    item.category,
                    item.expires_on,
                    status,
                ),
            )
            self._rows[row] = item
            if item is selected_item and not restored_selection:
                self.tree.selection_set(row)
                restored_selection = True

    def _refresh_recipes(self, reference: date) -> None:
        matches = match_recipes(self.inventory.available_names(reference), self.recipes)
        lines: list[str] = []
        for match in matches:
            lines.append(f"{match.recipe.name} — {match.coverage:.0%} ingredients available")
            lines.append("Missing: " + (", ".join(match.missing) if match.missing else "nothing"))
            lines.append("")
        self.recipe_text.delete("1.0", "end")
        self.recipe_text.insert("1.0", "\n".join(lines))

    def _check_date(self) -> None:
        self._date_refresh_id = None
        reference = self._today()
        if reference != self._display_date:
            self._refresh_views(reference)
        self._date_refresh_id = self.after(1000, self._check_date)

    def destroy(self) -> None:
        if self._date_refresh_id is not None:
            self.after_cancel(self._date_refresh_id)
            self._date_refresh_id = None
        super().destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Genius Kitchen")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".genius-kitchen")
    parser.add_argument(
        "--recipes",
        type=Path,
        default=None,
        help="Use a custom recipe JSON file instead of the bundled recipe data",
    )
    args = parser.parse_args()
    root = tk.Tk()
    root.withdraw()
    try:
        GeniusKitchenApp(root, JSONInventoryStore(args.data_dir / "inventory.json"), args.recipes)
    except (OSError, ValueError) as exc:
        messagebox.showerror(
            "Unable to open Genius Kitchen",
            f"{exc}\n\nCheck the file and try again. Your inventory has not been reset.",
            parent=root,
        )
        root.destroy()
        raise SystemExit(1) from exc
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
