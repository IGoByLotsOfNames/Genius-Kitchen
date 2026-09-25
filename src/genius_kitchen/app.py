from __future__ import annotations

import argparse
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox, ttk

from .inventory import Inventory
from .models import Ingredient
from .recipes import load_bundled_recipes, load_recipes, match_recipes
from .storage import JSONInventoryStore


class GeniusKitchenApp(ttk.Frame):
    def __init__(self, master: tk.Tk, store: JSONInventoryStore, recipes_path: Path | None = None) -> None:
        super().__init__(master, padding=18)
        self.store = store
        self.inventory = store.load()
        self.recipes = load_recipes(recipes_path) if recipes_path else load_bundled_recipes()
        self.grid(sticky="nsew")
        master.title("Genius Kitchen")
        master.geometry("900x610")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self._build()
        self._refresh_inventory()

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
        self.tree = ttk.Treeview(inventory_tab, columns=columns, show="headings", height=14)
        for column, label in zip(columns, ("Ingredient", "Quantity", "Category", "Expiry", "Status")):
            self.tree.heading(column, text=label)
        self.tree.grid(row=0, column=0, columnspan=5, sticky="nsew")

        self.name_var = tk.StringVar()
        self.quantity_var = tk.StringVar(value="1")
        self.unit_var = tk.StringVar(value="item")
        self.category_var = tk.StringVar(value="Other")
        self.expiry_var = tk.StringVar(value=date.today().isoformat())
        fields = (
            ("Name", self.name_var), ("Quantity", self.quantity_var),
            ("Unit", self.unit_var), ("Category", self.category_var),
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
        ttk.Button(recipe_tab, text="Refresh matches", command=self._refresh_recipes).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.recipe_text = tk.Text(recipe_tab, wrap="word", font=("Segoe UI", 11), padx=10, pady=10)
        self.recipe_text.grid(row=1, column=0, sticky="nsew")
        self._refresh_recipes()

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
        self.inventory.add(item)
        self.store.save(self.inventory)
        self._refresh_inventory()
        self._refresh_recipes()
        self.name_var.set("")

    def _remove(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        index = int(selection[0])
        self.inventory.remove(self.inventory.ingredients[index])
        self.store.save(self.inventory)
        self._refresh_inventory()
        self._refresh_recipes()

    def _refresh_inventory(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.inventory.ingredients):
            days = item.days_until_expiry()
            status = "Expired" if days < 0 else ("Expiring soon" if days <= 3 else f"{days} days")
            self.tree.insert(
                "", "end", iid=str(index),
                values=(item.name, f"{item.quantity:g} {item.unit}", item.category, item.expires_on, status),
            )

    def _refresh_recipes(self) -> None:
        matches = match_recipes(self.inventory.available_names(), self.recipes)
        lines: list[str] = []
        for match in matches:
            lines.append(f"{match.recipe.name} — {match.coverage:.0%} ingredients available")
            lines.append("Missing: " + (", ".join(match.missing) if match.missing else "nothing"))
            lines.append("")
        self.recipe_text.delete("1.0", "end")
        self.recipe_text.insert("1.0", "\n".join(lines))


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
    GeniusKitchenApp(root, JSONInventoryStore(args.data_dir / "inventory.json"), args.recipes)
    root.mainloop()


if __name__ == "__main__":
    main()
