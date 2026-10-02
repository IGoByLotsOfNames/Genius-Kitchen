from __future__ import annotations

import concurrent.futures
import http.client
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT))
import server  # noqa: E402

TEST_RUNTIME = WEB_ROOT / "tests" / "runtime"


class HTTPTests(unittest.TestCase):
    def setUp(self):
        TEST_RUNTIME.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="http-", dir=TEST_RUNTIME)
        self.root = Path(self.temporary.name)
        self.static = self.root / "static"
        self.static.mkdir()
        (self.static / "index.html").write_text("<h1>Test kitchen</h1>", encoding="utf-8")
        (self.static / "app.js").write_text("'use strict';", encoding="utf-8")
        (self.root / "private.json").write_text('["private"]', encoding="utf-8")
        self.clock = [date(2026, 10, 2)]
        self.httpd = server.create_server(
            self.root / "data", today=lambda: self.clock[0], static_dir=self.static
        )
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}
        )
        self.thread.start()
        self.state = self.request("GET", "/api/state")[2]

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join(timeout=3)
        self.httpd.server_close()
        self.assertFalse(self.thread.is_alive(), "HTTP server did not stop")
        self.temporary.cleanup()

    def request(self, method, path, body=None, *, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=3)
        request_headers = dict(headers or {})
        encoded = raw
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=encoded, headers=request_headers)
            response = connection.getresponse()
            content = response.read()
            response_headers = dict(response.getheaders())
            if content and response_headers.get("Content-Type", "").startswith("application/json"):
                content = json.loads(content)
            return response.status, response_headers, content
        finally:
            connection.close()

    def mutation_headers(self, state=None):
        state = state or self.state
        return {
            "Origin": self.httpd.origin,
            "X-CSRF-Token": state["csrf_token"],
            "If-Match": state["revision"],
        }

    def mutate(self, method, path, body=None, state=None):
        result = self.request(method, path, body, headers=self.mutation_headers(state))
        if result[0] == 200:
            self.state = result[2]
        return result

    def item(self, **changes):
        return {
            "name": "Milk",
            "quantity": 1,
            "unit": "litre",
            "category": "Dairy",
            "expires_on": "2026-10-04",
            **changes,
        }

    def test_blank_state_does_not_write_and_returns_complete_contract(self):
        self.assertEqual(
            set(self.state), {"revision", "csrf_token", "today", "items", "recipes", "demo_mode"}
        )
        self.assertEqual(self.state["items"], [])
        self.assertFalse(self.state["demo_mode"])
        self.assertEqual(len(self.state["recipes"]), 6)
        self.assertFalse(self.httpd.application.store.path.exists())
        self.assertEqual(
            set(self.state["recipes"][0]),
            {
                "id",
                "name",
                "coverage",
                "available",
                "missing",
                "ingredients",
                "instructions",
                "source_url",
            },
        )

    def test_crud_persists_export_uses_legacy_format_and_duplicate_identity(self):
        self.assertEqual(self.mutate("POST", "/api/items", self.item())[0], 200)
        first_revision = self.state["revision"]
        self.assertEqual(self.mutate("POST", "/api/items", self.item())[0], 200)
        self.assertNotEqual(first_revision, self.state["revision"])
        self.assertEqual(self.mutate("PATCH", "/api/items/1", self.item(quantity=2))[0], 200)
        self.assertEqual([i["quantity"] for i in self.state["items"]], [1, 2])
        self.assertEqual(self.mutate("DELETE", "/api/items/0")[0], 200)
        self.assertEqual(self.state["items"][0]["quantity"], 2)
        code, headers, exported = self.request("GET", "/api/export")
        self.assertEqual(code, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(exported, [self.item(quantity=2)])
        self.assertEqual(
            json.loads(self.httpd.application.store.path.read_text(encoding="utf-8")), exported
        )
        reloaded = server.JSONInventoryStore(self.httpd.application.store.path).load()
        self.assertEqual(reloaded.ingredients[0].quantity, 2)

    def test_expiry_order_status_and_recipe_matching(self):
        code, _, state = self.mutate("POST", "/api/demo", {})
        self.assertEqual(code, 200)
        self.assertEqual(len(state["items"]), 9)
        self.assertEqual(
            (state["items"][0]["name"], state["items"][0]["status"]), ("Milk", "expired")
        )
        egg = next(i for i in state["items"] if i["name"] == "Egg")
        self.assertEqual((egg["days_until_expiry"], egg["status"]), (0, "soon"))
        self.assertEqual(state["recipes"][0]["coverage"], 1)
        self.assertEqual(self.mutate("POST", "/api/demo", {})[0], 409)
        self.assertEqual(len(self.request("GET", "/api/state")[2]["items"]), 9)

    def test_import_explicitly_replaces_and_accepts_legacy_default_category(self):
        self.mutate("POST", "/api/items", self.item())
        legacy = self.item(name="Rice")
        del legacy["category"]
        code, _, state = self.mutate("POST", "/api/import", {"items": [legacy]})
        self.assertEqual(code, 200)
        self.assertEqual([i["name"] for i in state["items"]], ["Rice"])
        self.assertEqual(state["items"][0]["category"], "Other")
        self.assertEqual(self.mutate("POST", "/api/import", {"items": []})[0], 200)
        self.assertEqual(self.state["items"], [])

    def test_invalid_item_shapes_and_values_never_write(self):
        invalid = [self.item(quantity=q) for q in [True, 0, -1, "1", float("inf")]]
        invalid += [
            self.item(name="  "),
            self.item(expires_on="not-a-date"),
            self.item(unit=3),
            {},
            [],
            None,
        ]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.mutate("POST", "/api/items", body)[0], 400)
                self.assertFalse(self.httpd.application.store.path.exists())

    def test_invalid_import_preserves_saved_bytes(self):
        self.mutate("POST", "/api/items", self.item())
        original = self.httpd.application.store.path.read_bytes()
        for body in [
            {"items": [self.item(name="Egg"), self.item(quantity=-1)]},
            {"items": {}},
            {},
            [],
        ]:
            self.assertEqual(self.mutate("POST", "/api/import", body)[0], 400)
            self.assertEqual(self.httpd.application.store.path.read_bytes(), original)

    def test_missing_wrong_and_nonascii_csrf_are_rejected(self):
        for token in [None, "wrong", "\u00e9"]:
            headers = self.mutation_headers()
            if token is None:
                del headers["X-CSRF-Token"]
            else:
                headers["X-CSRF-Token"] = token
            self.assertEqual(
                self.request("POST", "/api/items", self.item(), headers=headers)[0], 403
            )
        self.assertFalse(self.httpd.application.store.path.exists())

    def test_missing_wrong_and_null_origins_are_rejected(self):
        for origin in [
            None,
            "https://example.com",
            "null",
            "http://localhost:" + str(self.httpd.server_port),
        ]:
            headers = self.mutation_headers()
            if origin is None:
                del headers["Origin"]
            else:
                headers["Origin"] = origin
            self.assertEqual(
                self.request("POST", "/api/items", self.item(), headers=headers)[0], 403
            )
        self.assertEqual(
            self.request("GET", "/api/state", headers={"Origin": "https://example.com"})[0], 403
        )

    def test_host_restriction_and_cors_preflight(self):
        for host in ["example.com", "localhost:" + str(self.httpd.server_port), "127.0.0.1:1"]:
            self.assertEqual(self.request("GET", "/api/state", headers={"Host": host})[0], 403)
        code, headers, _ = self.request(
            "OPTIONS", "/api/items", headers={"Origin": "https://example.com"}
        )
        self.assertEqual(code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_stale_missing_and_quoted_revision(self):
        old = dict(self.state)
        self.mutate("POST", "/api/items", self.item())
        self.assertEqual(self.mutate("DELETE", "/api/items/0", state=old)[0], 409)
        headers = self.mutation_headers()
        del headers["If-Match"]
        self.assertEqual(self.request("DELETE", "/api/items/0", headers=headers)[0], 409)
        headers["If-Match"] = '"' + self.state["revision"] + '"'
        self.assertEqual(self.request("DELETE", "/api/items/0", headers=headers)[0], 200)

    def test_external_disk_edit_and_date_change_invalidate_revision(self):
        store = self.httpd.application.store
        store.save(server.Inventory([server.Ingredient.from_dict(self.item(name="External"))]))
        self.assertEqual(self.mutate("POST", "/api/items", self.item())[0], 409)
        self.state = self.request("GET", "/api/state")[2]
        self.assertEqual(self.state["items"][0]["name"], "External")
        self.clock[0] += timedelta(days=1)
        self.assertEqual(self.mutate("DELETE", "/api/items/0")[0], 409)
        new_state = self.request("GET", "/api/state")[2]
        self.assertEqual(new_state["today"], "2026-10-03")
        self.assertEqual(new_state["items"][0]["days_until_expiry"], 1)

    def test_simultaneous_same_revision_mutations_only_one_succeeds(self):
        barrier = threading.Barrier(2)
        headers = self.mutation_headers()

        def add(name):
            barrier.wait(timeout=3)
            return self.request("POST", "/api/items", self.item(name=name), headers=headers)[0]

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(add, ["A", "B"]))
        self.assertEqual(sorted(results), [200, 409])
        self.assertEqual(len(self.request("GET", "/api/state")[2]["items"]), 1)

    def test_save_failure_returns_error_and_retains_disk_and_state(self):
        self.mutate("POST", "/api/items", self.item())
        original = self.httpd.application.store.path.read_bytes()
        with patch.object(self.httpd.application.store, "save", side_effect=OSError("injected")):
            self.assertEqual(self.mutate("PATCH", "/api/items/0", self.item(quantity=3))[0], 500)
        self.assertEqual(self.httpd.application.store.path.read_bytes(), original)
        self.assertEqual(self.request("GET", "/api/state")[2], self.state)

    def test_malformed_disk_after_startup_is_reported_without_reset(self):
        path = self.httpd.application.store.path
        path.parent.mkdir()
        malformed = b'{"broken":'
        path.write_bytes(malformed)
        self.assertEqual(self.request("GET", "/api/state")[0], 500)
        self.assertEqual(self.mutate("POST", "/api/items", self.item())[0], 500)
        self.assertEqual(path.read_bytes(), malformed)

    def test_traversal_and_nonstatic_files_are_not_served(self):
        for path in [
            "/../private.json",
            "/%2e%2e/private.json",
            "/%2e%2e%5cprivate.json",
            "/%00",
            "/server.py",
            "/core/genius_kitchen/models.py",
        ]:
            with self.subTest(path=path):
                code, _, result = self.request("GET", path)
                self.assertIn(code, [400, 404])
                self.assertIn("error", result)

    def test_static_mime_security_headers_and_head(self):
        code, headers, body = self.request("GET", "/?tab=pantry")
        self.assertEqual(code, 200)
        self.assertIn(b"Test kitchen", body)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(
            self.request("GET", "/app.js")[1]["Content-Type"], "text/javascript; charset=utf-8"
        )
        self.assertEqual(self.request("HEAD", "/")[2], b"")

    def test_invalid_json_body_and_size_limit(self):
        headers = {**self.mutation_headers(), "Content-Type": "application/json"}
        for raw in [b"{", b"\xff", b'{"quantity":NaN}', b"[" * 2000]:
            self.assertEqual(self.request("POST", "/api/items", headers=headers, raw=raw)[0], 400)
        oversized_headers = {**headers, "Content-Length": str(server.MAX_BODY + 1)}
        self.assertEqual(
            self.request("POST", "/api/items", headers=oversized_headers, raw=b"")[0], 400
        )
        headers["Content-Type"] = "text/plain"
        self.assertEqual(self.request("POST", "/api/items", headers=headers, raw=b"{}")[0], 400)

    def test_invalid_item_ids_and_unknown_routes(self):
        for item_id in ["-1", "abc", "01", "0/1"]:
            self.assertEqual(self.mutate("DELETE", "/api/items/" + item_id)[0], 400)
        self.assertEqual(self.mutate("DELETE", "/api/items/0")[0], 409)
        self.assertEqual(self.request("GET", "/api/unknown")[0], 404)
        self.assertEqual(self.mutate("POST", "/api/unknown", {})[0], 404)

    def test_shutdown_requires_authorization_then_stops_server(self):
        self.assertEqual(self.request("POST", "/api/shutdown", {})[0], 403)
        self.assertTrue(self.thread.is_alive())
        self.assertEqual(self.mutate("POST", "/api/shutdown", {})[0], 200)
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())


class StartupTests(unittest.TestCase):
    def setUp(self):
        TEST_RUNTIME.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="startup-", dir=TEST_RUNTIME)
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_malformed_existing_file_refuses_startup_and_preserves_bytes(self):
        path = self.root / "inventory.json"
        path.write_bytes(b"not json")
        with self.assertRaises(ValueError):
            server.create_server(self.root)
        self.assertEqual(path.read_bytes(), b"not json")

    def test_demo_sessions_are_unique_and_relative_to_today(self):
        first = server.create_server(self.root, demo=True, today=lambda: date(2026, 1, 5))
        second = server.create_server(self.root, demo=True, today=lambda: date(2026, 1, 6))
        try:
            self.assertNotEqual(first.application.store.path, second.application.store.path)
            self.assertEqual(
                first.application.store.load().ingredients[0].expires_on, date(2026, 1, 4)
            )
            self.assertEqual(
                second.application.store.load().ingredients[0].expires_on, date(2026, 1, 5)
            )
            self.assertTrue(first.application.demo_mode)
            self.assertFalse((self.root / "inventory.json").exists())
        finally:
            first.server_close()
            second.server_close()

    def test_default_normal_storage_is_separate_from_desktop(self):
        with patch.object(Path, "home", return_value=self.root):
            store = server.prepare_store(None, False, date(2026, 1, 1))
        self.assertEqual(store.path, self.root / ".genius-kitchen-web" / "inventory.json")
        self.assertFalse(store.path.exists())

    def test_frozen_demo_runtime_uses_executable_directory(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(self.root / "Kitchen.exe")),
        ):
            self.assertEqual(server.default_demo_parent(), self.root / "runtime")

    def test_cli_from_other_cwd_writes_ready_file_and_exits_via_http(self):
        ready = self.root / "ready data.json"
        diagnostics = self.root / "diagnostics.json"
        process = subprocess.Popen(
            [
                getattr(sys, "_base_executable", sys.executable),
                "-B",
                str(WEB_ROOT / "server.py"),
                "--no-browser",
                "--demo",
                "--data-dir",
                str(self.root / "demo data"),
                "--ready-file",
                str(ready),
                "--diagnostics-file",
                str(diagnostics),
            ],
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        lines = queue.Queue()
        reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            self.assertIn("Genius Kitchen: http://127.0.0.1:", lines.get(timeout=8))
            metadata = json.loads(ready.read_text(encoding="utf-8"))
            self.assertEqual(metadata["pid"], process.pid)
            inspected = json.loads(diagnostics.read_text(encoding="utf-8"))
            self.assertFalse(inspected["frozen"])
            self.assertFalse(inspected["tkinter_loaded"])
            self.assertEqual(Path(inspected["resource_root"]), WEB_ROOT)
            self.assertEqual(len(inspected["module_origins"]), 5)
            from urllib.parse import urlsplit

            url = urlsplit(metadata["url"])
            connection = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
            connection.request("GET", "/api/state")
            response = connection.getresponse()
            state = json.loads(response.read())
            connection.close()
            self.assertTrue(state["demo_mode"])
            self.assertEqual(len(state["items"]), 9)
            connection = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
            connection.request(
                "POST",
                "/api/shutdown",
                body="{}",
                headers={
                    "Origin": metadata["url"].rstrip("/"),
                    "X-CSRF-Token": state["csrf_token"],
                    "If-Match": state["revision"],
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            connection.close()
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)
            reader.join(timeout=3)

    def test_windowed_launch_handles_absent_output_streams(self):
        with (
            patch.object(sys, "stdout", None),
            patch.object(sys, "stderr", None),
            patch.object(server.webbrowser, "open", return_value=True) as browser,
            patch.object(server.LocalServer, "serve_forever"),
        ):
            result = server.main(["--data-dir", str(self.root)])
        self.assertEqual(result, 0)
        self.assertTrue(browser.call_args.args[0].startswith("http://127.0.0.1:"))

    def test_headless_startup_error_is_logged_without_resetting_inventory(self):
        inventory = self.root / "inventory.json"
        inventory.write_bytes(b"broken")
        with (
            patch.object(sys, "stderr", None),
            patch.object(server, "default_demo_parent", return_value=self.root / "runtime"),
        ):
            result = server.main(["--no-browser", "--data-dir", str(self.root)])
        self.assertEqual(result, 1)
        self.assertEqual(inventory.read_bytes(), b"broken")
        self.assertIn(
            "Your inventory has not been reset",
            (self.root / "runtime/last-error.txt").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
