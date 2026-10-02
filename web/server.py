"""Genius Kitchen's local browser application (Python 3.11+, standard library)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
import webbrowser
from collections.abc import Callable
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote, urlsplit

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()
CORE_ROOT = RESOURCE_ROOT / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE_ROOT))
from genius_kitchen.inventory import Inventory  # noqa: E402
from genius_kitchen.models import Ingredient  # noqa: E402
from genius_kitchen.recipes import load_bundled_recipes, match_recipes  # noqa: E402
from genius_kitchen.storage import JSONInventoryStore  # noqa: E402

MAX_BODY = 1024 * 1024
ITEM_FIELDS = {"name", "quantity", "unit", "category", "expires_on"}
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
)


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def sample_inventory(reference: date) -> Inventory:
    rows = json.loads((RESOURCE_ROOT / "demo_sample.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Demo pantry must be a JSON array")
    result = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get("expires_in_days")) is not int:
            raise ValueError("Demo pantry entries need integer expiry offsets")
        record = dict(row)
        record["expires_on"] = (
            reference + timedelta(days=record.pop("expires_in_days"))
        ).isoformat()
        result.append(Ingredient.from_dict(record))
    return Inventory(result)


def default_demo_parent() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "runtime"
    return Path(__file__).resolve().parent / "runtime"


def prepare_store(data_dir: Path | None, demo: bool, reference: date) -> JSONInventoryStore:
    if demo:
        parent = data_dir if data_dir is not None else default_demo_parent()
        parent.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="demo-", dir=parent))
        store = JSONInventoryStore(directory / "inventory.json")
        store.save(sample_inventory(reference))
        return store
    directory = data_dir if data_dir is not None else Path.home() / ".genius-kitchen-web"
    return JSONInventoryStore(directory / "inventory.json")


def inventory_revision(inventory: Inventory, reference: date) -> str:
    # Include the date so a mutation based on yesterday's expiry view is stale.
    payload = {
        "today": reference.isoformat(),
        "items": [i.to_dict() for i in inventory.ingredients],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class Application:
    def __init__(
        self,
        store: JSONInventoryStore,
        *,
        demo: bool = False,
        today: Callable[[], date] = date.today,
        static_dir: Path | None = None,
    ):
        self.store = store
        self.demo_mode = demo
        self.today = today
        self.static_dir = (static_dir or RESOURCE_ROOT / "static").resolve()
        self.csrf_token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.recipes = load_bundled_recipes()
        # Refuse malformed/unreadable data at startup, without resetting it.
        self.store.load()

    def state(self, inventory: Inventory, reference: date) -> dict:
        items = []
        for index, item in enumerate(inventory.ingredients):
            days = item.days_until_expiry(reference)
            items.append(
                {
                    **item.to_dict(),
                    "id": str(index),
                    "days_until_expiry": days,
                    "status": "expired" if days < 0 else ("soon" if days <= 3 else "fresh"),
                }
            )
        recipe_ids = {id(recipe): str(index) for index, recipe in enumerate(self.recipes)}
        matches = match_recipes(inventory.available_names(reference), self.recipes)
        recipes = [
            {
                "id": recipe_ids[id(match.recipe)],
                "name": match.recipe.name,
                "coverage": match.coverage,
                "available": list(match.available),
                "missing": list(match.missing),
                "ingredients": list(match.recipe.ingredients),
                "instructions": list(match.recipe.instructions),
                "source_url": match.recipe.source_url,
            }
            for match in matches
        ]
        return {
            "revision": inventory_revision(inventory, reference),
            "csrf_token": self.csrf_token,
            "today": reference.isoformat(),
            "items": items,
            "recipes": recipes,
            "demo_mode": self.demo_mode,
        }


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, application: Application, port: int = 0):
        self.application = application
        super().__init__(("127.0.0.1", port), Handler)
        self.authority = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.authority}"


class Handler(BaseHTTPRequestHandler):
    server: LocalServer
    server_version = "GeniusKitchen"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Do not log request contents or tokens.
        pass

    def respond(self, status: int, body: bytes, content_type: str, *, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Connection", "close")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(body)

    def json_response(self, status: int, value: object, *, headers: dict | None = None):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.respond(status, body, "application/json; charset=utf-8", headers=headers)

    def guard(self, *, mutation: bool):
        hosts = self.headers.get_all("Host", [])
        if hosts != [self.server.authority]:
            raise APIError(403, "This application only accepts its local address.")
        origins = self.headers.get_all("Origin", [])
        if (mutation and origins != [self.server.origin]) or (
            origins and origins != [self.server.origin]
        ):
            raise APIError(403, "Request origin is not allowed.")
        if mutation:
            tokens = self.headers.get_all("X-CSRF-Token", [])
            if len(tokens) != 1 or not secrets.compare_digest(
                tokens[0].encode("utf-8"), self.server.application.csrf_token.encode("utf-8")
            ):
                raise APIError(403, "Refresh the page before changing your inventory.")

    def read_json(self):
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "Chunked request bodies are not supported.")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            raise APIError(400, "Provide a single Content-Length.")
        try:
            length = int(lengths[0]) if lengths else 0
        except ValueError as exc:
            raise APIError(400, "Invalid Content-Length.") from exc
        if length < 0 or length > MAX_BODY:
            raise APIError(400, "Request body must be at most 1 MiB.")
        if length == 0:
            return {}
        if self.headers.get_content_type() != "application/json":
            raise APIError(400, "Use application/json for request bodies.")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise APIError(400, "Incomplete request body.")
        try:

            def reject_constant(value):
                raise ValueError("JSON numbers must be finite")

            return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise APIError(400, "Invalid JSON request body.") from exc

    def route_path(self) -> str:
        try:
            parsed = urlsplit(self.path)
        except ValueError as exc:
            raise APIError(400, "Invalid request path.") from exc
        if parsed.scheme or parsed.netloc:
            raise APIError(400, "Use a relative request path.")
        path = unquote(parsed.path)
        if "\\" in path or "\x00" in path or any(p in {".", ".."} for p in path.split("/")):
            raise APIError(400, "Invalid request path.")
        return path

    def get(self):
        self.guard(mutation=False)
        path = self.route_path()
        app = self.server.application
        if path in {"/api/state", "/api/export"}:
            with app.lock:
                inventory = app.store.load()
                if path == "/api/state":
                    state = app.state(inventory, app.today())
                    self.json_response(200, state, headers={"ETag": f'"{state["revision"]}"'})
                else:
                    self.json_response(
                        200,
                        [i.to_dict() for i in inventory.ingredients],
                        headers={
                            "Content-Disposition": 'attachment; filename="genius-kitchen-inventory.json"',
                        },
                    )
            return
        if path.startswith("/api/"):
            raise APIError(404, "Unknown API endpoint.")
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (app.static_dir / relative).resolve()
        if not target.is_relative_to(app.static_dir) or target.suffix.lower() not in STATIC_TYPES:
            raise APIError(404, "File not found.")
        if not target.is_file():
            raise APIError(404, "File not found.")
        self.respond(200, target.read_bytes(), STATIC_TYPES[target.suffix.lower()])

    def mutate(self):
        self.guard(mutation=True)
        path = self.route_path()
        body = self.read_json()
        app = self.server.application
        with app.lock:
            inventory = app.store.load()
            reference = app.today()
            revisions = self.headers.get_all("If-Match", [])
            expected = inventory_revision(inventory, reference)
            if len(revisions) != 1 or revisions[0] not in {expected, f'"{expected}"'}:
                raise APIError(409, "Inventory changed. Refresh the page and try again.")
            items = list(inventory.ingredients)
            shutting_down = False
            try:
                if self.command == "POST" and path == "/api/items":
                    items.append(self.item_body(body))
                elif self.command in {"PATCH", "DELETE"} and path.startswith("/api/items/"):
                    item_id = path[len("/api/items/") :]
                    if (
                        not item_id.isascii()
                        or not item_id.isdigit()
                        or str(int(item_id)) != item_id
                    ):
                        raise APIError(400, "Invalid ingredient ID.")
                    index = int(item_id)
                    if index >= len(items):
                        raise APIError(409, "Ingredient no longer exists. Refresh the page.")
                    if self.command == "PATCH":
                        items[index] = self.item_body(body)
                    else:
                        if body != {}:
                            raise APIError(400, "DELETE does not accept ingredient data.")
                        del items[index]
                elif self.command == "POST" and path == "/api/import":
                    if (
                        not isinstance(body, dict)
                        or set(body) != {"items"}
                        or not isinstance(body["items"], list)
                    ):
                        raise APIError(400, "Import requires an object containing an items array.")
                    items = [Ingredient.from_dict(item) for item in body["items"]]
                elif self.command == "POST" and path == "/api/demo":
                    if body != {}:
                        raise APIError(400, "Demo loading requires an empty object.")
                    if items:
                        raise APIError(409, "Demo data can only be loaded into an empty inventory.")
                    items = list(sample_inventory(reference).ingredients)
                elif self.command == "POST" and path == "/api/shutdown":
                    if body != {}:
                        raise APIError(400, "Shutdown requires an empty object.")
                    shutting_down = True
                else:
                    raise APIError(404, "Unknown API endpoint.")
            except ValueError as exc:
                raise APIError(400, str(exc)) from exc
            candidate = Inventory(items)
            # Construct/validate the response before persistence, so a rendering
            # error cannot produce a reported failure after silently saving data.
            state = app.state(candidate, reference)
            if not shutting_down:
                app.store.save(candidate)
            self.json_response(200, state, headers={"ETag": f'"{state["revision"]}"'})
            if shutting_down:
                threading.Thread(target=self.server.shutdown, daemon=True).start()

    @staticmethod
    def item_body(body) -> Ingredient:
        if not isinstance(body, dict) or set(body) != ITEM_FIELDS:
            raise APIError(
                400, "An ingredient requires name, quantity, unit, category and expires_on."
            )
        return Ingredient.from_dict(body)

    def dispatch(self, action):
        try:
            action()
        except APIError as exc:
            self.json_response(exc.status, {"error": str(exc)})
        except (OSError, ValueError, RecursionError):
            self.json_response(
                500,
                {
                    "error": "Unable to read or save inventory. Your existing data has not been reset."
                },
            )

    def do_GET(self):
        self.dispatch(self.get)

    def do_HEAD(self):
        self.dispatch(self.get)

    def do_POST(self):
        self.dispatch(self.mutate)

    def do_PATCH(self):
        self.dispatch(self.mutate)

    def do_DELETE(self):
        self.dispatch(self.mutate)

    def do_OPTIONS(self):
        def reject():
            self.guard(mutation=False)
            raise APIError(403, "Cross-origin requests are not supported.")

        self.dispatch(reject)


def create_server(
    data_dir: Path | None = None,
    *,
    port: int = 0,
    demo: bool = False,
    today: Callable[[], date] = date.today,
    static_dir: Path | None = None,
) -> LocalServer:
    store = prepare_store(data_dir, demo, today())
    app = Application(store, demo=demo, today=today, static_dir=static_dir)
    return LocalServer(app, port)


def write_diagnostics(path: Path) -> None:
    """Explicit packaging diagnostic; never written during an ordinary launch."""
    resource_paths = [RESOURCE_ROOT / "demo_sample.json"]
    for directory in (CORE_ROOT, RESOURCE_ROOT / "static"):
        resource_paths.extend(
            p for p in directory.rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    module_names = (
        "genius_kitchen",
        "genius_kitchen.inventory",
        "genius_kitchen.models",
        "genius_kitchen.recipes",
        "genius_kitchen.storage",
    )
    recipe_data = files("genius_kitchen").joinpath("data", "recipes.json")
    result = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "resource_root": str(RESOURCE_ROOT),
        "executable": sys.executable,
        "module_origins": {
            name: getattr(sys.modules[name], "__file__", None) for name in module_names
        },
        "resource_sha256": {
            p.relative_to(RESOURCE_ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(resource_paths)
        },
        "tkinter_loaded": "tkinter" in sys.modules or "_tkinter" in sys.modules,
        "recipe_data_origin": str(recipe_data),
        "recipe_data_sha256": hashlib.sha256(recipe_data.read_bytes()).hexdigest(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def report_startup_problem(message: str, *, show_dialog: bool) -> None:
    """Keep a useful error visible when a windowed EXE has no output streams."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    try:
        directory = default_demo_parent()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "last-error.txt").write_text(message + "\n", encoding="utf-8")
    except OSError:
        pass
    if show_dialog and getattr(sys, "frozen", False) and sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Genius Kitchen", 0x10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="Loopback port; 0 chooses a free port")
    parser.add_argument("--data-dir", type=Path, help="Inventory directory, or demo session parent")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--demo", action="store_true", help="Create a fresh isolated sample session"
    )
    parser.add_argument(
        "--ready-file", type=Path, help="Write the bound URL and process ID as JSON"
    )
    parser.add_argument(
        "--diagnostics-file", type=Path, help="Write explicit packaging diagnostics"
    )
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    server = None
    try:
        server = create_server(args.data_dir, port=args.port, demo=args.demo)
        url = server.origin + "/"
        if args.diagnostics_file:
            write_diagnostics(args.diagnostics_file)
        if args.ready_file:
            args.ready_file.parent.mkdir(parents=True, exist_ok=True)
            args.ready_file.write_text(
                json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8"
            )
        if sys.stdout is not None:
            print(f"Genius Kitchen: {url}", flush=True)
        if not args.no_browser:
            try:
                opened = webbrowser.open(url)
            except (OSError, webbrowser.Error):
                opened = False
            if not opened:
                report_startup_problem(f"Open {url} in your browser to continue.", show_dialog=True)
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as exc:
        report_startup_problem(
            f"Unable to start Genius Kitchen: {exc}\n\nCheck the inventory file and selected port. "
            "Your inventory has not been reset. Retry with --demo for a separate sample session.",
            show_dialog=not args.no_browser,
        )
        return 1
    finally:
        if server is not None:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
