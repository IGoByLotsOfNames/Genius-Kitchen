"""Packaged entry point for the unchanged Genius Kitchen Tk application."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(__file__).resolve().parent
if not FROZEN:
    working = RESOURCE_ROOT.parent
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(working / "src"), str(working)]

import demo as demo_support  # noqa: E402
from genius_kitchen import app as ui  # noqa: E402
from genius_kitchen.recipes import load_bundled_recipes  # noqa: E402
from genius_kitchen.storage import JSONInventoryStore  # noqa: E402


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Genius Kitchen desktop application")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help="start a separate, fresh sample pantry")
    modes.add_argument("--smoke-test", action="store_true", help="run hidden packaged-GUI checks")
    parser.add_argument(
        "--data-dir", type=Path, help="inventory directory for normal use or a fresh smoke test"
    )
    parser.add_argument("--recipes", type=Path, help="custom recipe JSON for normal use")
    parser.add_argument(
        "--report", type=Path, help="required JSON report destination for --smoke-test"
    )
    args = parser.parse_args(argv)
    if args.demo and args.data_dir:
        parser.error("--demo creates its own fresh folder; do not combine it with --data-dir")
    if args.recipes and (args.demo or args.smoke_test):
        parser.error("--recipes is for normal use; sample modes use the bundled recipes")
    if args.smoke_test and (args.data_dir is None or args.report is None):
        parser.error("--smoke-test requires --data-dir and --report")
    if args.report and not args.smoke_test:
        parser.error("--report is only used by --smoke-test")

    report = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "passed": False,
        "frozen": FROZEN,
        "python": sys.version,
        "checks": [],
        "errors": [],
        "scope": "Real hidden Tk widgets, button callbacks, bundled data and isolated persistence; no visual QA.",
    }
    root = None
    original_showerror = ui.messagebox.showerror
    reference = date.today()
    demo_support.configure_tk_runtime(ui.tk)

    def fail_dialog(*unused_args, **unused_kwargs):
        raise RuntimeError("Unexpected error dialog during packaged smoke test")

    def callback_error(kind, error, tb):
        report["errors"].append("".join(traceback.format_exception(kind, error, tb)))
        if not args.smoke_test:
            original_showerror("Genius Kitchen error", str(error), parent=root)
        root.quit()

    try:
        # Hidden immediately; normal launches are shown only after successful loading.
        root = ui.tk.Tk()
        root.withdraw()
        root.protocol("WM_DELETE_WINDOW", root.quit)
        root.report_callback_exception = callback_error
        icon = RESOURCE_ROOT / "assets" / "GeniusKitchen.ico"
        if icon.is_file():
            root.iconbitmap(default=str(icon))
        if args.smoke_test:
            ui.messagebox.showerror = fail_dialog
            data_dir = args.data_dir.resolve()
            if data_dir.exists():
                raise ValueError(
                    "Smoke-test data directory must be new; existing data is never overwritten"
                )
            data_dir.mkdir(parents=True, exist_ok=False)
        elif args.demo:
            application_dir = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_ROOT
            demos = application_dir / "demo-runs"
            demos.mkdir(parents=True, exist_ok=True)
            data_dir = Path(tempfile.mkdtemp(prefix="pantry-", dir=demos))
        else:
            data_dir = args.data_dir or (Path.home() / ".genius-kitchen")

        store = JSONInventoryStore(data_dir / "inventory.json")
        if args.demo or args.smoke_test:
            inventory = demo_support.sample_inventory(reference)
            demo_support.verify_sample(inventory, reference)
            store.save(inventory)
        report["data_file"] = str(store.path.resolve())
        app = ui.GeniusKitchenApp(
            root, store, args.recipes, today=(lambda: reference) if args.smoke_test else None
        )
        root.title("Genius Kitchen - Demo" if args.demo else "Genius Kitchen")
        root.update_idletasks()

        if args.smoke_test:
            report["application_module"] = ui.__file__
            report["packaged_build_info"] = json.loads(
                (RESOURCE_ROOT / "assets/build-info.json").read_text(encoding="utf-8")
            )
            before = store.path.read_bytes()
            report["bundled_recipe_count"] = len(load_bundled_recipes())
            if report["bundled_recipe_count"] != 6:
                raise RuntimeError("Expected six bundled recipes")
            report["checks"].append("application initialized real Tk with six bundled recipes")

            def check_and_quit():
                demo_support.smoke_check(app, reference)
                report["checks"].extend(
                    [
                        "nine sample rows with expired Milk and expected recipe ranking",
                        "real Add ingredient button saved fresh Milk and updated pancakes to 100%",
                        "real Remove selected button restored nine rows and pancakes to 75%",
                    ]
                )
                if store.path.read_bytes() != before:
                    raise RuntimeError(
                        "Adding and removing the test ingredient changed original sample bytes"
                    )
                app.destroy()
                reopened = ui.GeniusKitchenApp(root, store, today=lambda: reference)
                root.update_idletasks()
                demo_support.verify_sample(reopened.inventory, reference)
                if len(reopened.tree.get_children()) != 9:
                    raise RuntimeError("Reopened view did not recover persisted inventory")
                report["checks"].append(
                    "fresh application view reloaded identical persisted sample bytes"
                )
                root.quit()

            root.after_idle(check_and_quit)
        else:
            root.deiconify()
        root.mainloop()
    except Exception as exc:
        report["errors"].append(traceback.format_exc())
        if not args.smoke_test:
            original_showerror(
                "Unable to open Genius Kitchen",
                f"{exc}\n\nExisting inventory has not been reset.",
                parent=root,
            )
    finally:
        if root is not None:
            try:
                root.destroy()
            except ui.tk.TclError as exc:
                report["errors"].append(f"Window cleanup failed: {exc}")
        ui.messagebox.showerror = original_showerror
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        report["passed"] = not report["errors"]
        if args.smoke_test:
            write_report(args.report.resolve(), report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
