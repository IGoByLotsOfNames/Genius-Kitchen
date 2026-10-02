"""Exercise the actual frozen web EXE using a fresh isolated HTTP demo session."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

WEB = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    executable = WEB / "dist/GeniusKitchen-Web.exe"
    if not executable.is_file():
        raise FileNotFoundError("Build GeniusKitchen-Web.exe first")
    output = WEB / "verification" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=False)
    temporary = output / "temporary"
    temporary.mkdir()
    ready = output / "ready.json"
    diagnostics = output / "packaged-diagnostics.json"
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "TCL_LIBRARY", "TK_LIBRARY"):
        environment.pop(name, None)
    environment.update(TEMP=str(temporary), TMP=str(temporary), PYTHONDONTWRITEBYTECODE="1")
    command = [
        str(executable),
        "--demo",
        "--no-browser",
        "--data-dir",
        str(output / "pantry sessions"),
        "--ready-file",
        str(ready),
        "--diagnostics-file",
        str(diagnostics),
    ]
    process = subprocess.Popen(
        command,
        cwd=output,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    checks = []
    state = None
    origin = None
    report = {
        "passed": False,
        "executable": str(executable),
        "sha256": digest(executable),
        "verification_script_sha256": digest(Path(__file__)),
        "command": command,
        "external_python_and_tcl_environment_removed": True,
        "checks": checks,
        "user_inventory_accessed": False,
    }

    def check(condition, message):
        if not condition:
            raise AssertionError(message)
        checks.append(message)

    def request(method, path, body=None, *, authenticated=False, override=None):
        endpoint = urlsplit(origin)
        connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=5)
        headers = {}
        if authenticated:
            headers.update(
                {
                    "Origin": origin,
                    "X-CSRF-Token": state["csrf_token"],
                    "If-Match": state["revision"],
                }
            )
        raw = None
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        headers.update(override or {})
        try:
            connection.request(method, path, body=raw, headers=headers)
            response = connection.getresponse()
            data = response.read()
            result_headers = dict(response.getheaders())
            if data and result_headers.get("Content-Type", "").startswith("application/json"):
                data = json.loads(data)
            return response.status, result_headers, data
        finally:
            connection.close()

    try:
        deadline = time.monotonic() + 45
        while True:
            if ready.is_file():
                try:
                    metadata = json.loads(ready.read_text(encoding="utf-8"))
                    break
                except (OSError, ValueError):
                    pass
            if process.poll() is not None:
                raise RuntimeError(f"EXE exited before readiness ({process.returncode})")
            if time.monotonic() >= deadline:
                raise TimeoutError("EXE did not become ready within 45 seconds")
            # Bounded readiness polling, never used to guess completion of an operation.
            threading.Event().wait(0.05)
        origin = metadata["url"].rstrip("/")
        check(urlsplit(origin).hostname == "127.0.0.1", "bound URL is loopback only")
        check(
            isinstance(metadata["pid"], int) and metadata["pid"] > 0,
            "ready file reports a process ID",
        )
        code, headers, state = request("GET", "/api/state")
        check(
            code == 200 and state["demo_mode"] and len(state["items"]) == 9,
            "fresh demo contains nine ingredients",
        )
        check(len(state["recipes"]) == 6, "six bundled recipes load in the frozen executable")
        check(headers.get("X-Content-Type-Options") == "nosniff", "API has nosniff response header")
        check(
            next(i for i in state["items"] if i["name"] == "Milk")["status"] == "expired",
            "relative demo expiry is applied",
        )
        initial_revision = state["revision"]
        item = {
            "name": "Milk",
            "quantity": 1,
            "unit": "litre",
            "category": "Dairy",
            "expires_on": state["today"],
        }
        code, _, added = request("POST", "/api/items", item, authenticated=True)
        check(code == 200 and len(added["items"]) == 10, "POST adds an ingredient")
        state = added
        pancakes = next(r for r in state["recipes"] if r["name"] == "Banana Oat Pancakes")
        check(pancakes["coverage"] == 1, "fresh milk raises pancake coverage to 100 percent")
        added_item = next(
            i for i in state["items"] if i["name"] == "Milk" and i["days_until_expiry"] == 0
        )
        code, _, edited = request(
            "PATCH", f"/api/items/{added_item['id']}", {**item, "quantity": 2}, authenticated=True
        )
        check(
            code == 200
            and any(i["name"] == "Milk" and i["quantity"] == 2 for i in edited["items"]),
            "PATCH updates quantity",
        )
        state = edited
        check(
            request(
                "POST",
                "/api/items",
                item,
                authenticated=True,
                override={"If-Match": initial_revision},
            )[0]
            == 409,
            "stale revision is rejected",
        )
        check(
            request("POST", "/api/items", item)[0] == 403,
            "mutation without Origin/token is rejected",
        )
        check(
            request(
                "POST",
                "/api/items",
                item,
                authenticated=True,
                override={"Origin": "https://example.com"},
            )[0]
            == 403,
            "foreign Origin is rejected",
        )
        check(
            request(
                "POST", "/api/items", item, authenticated=True, override={"X-CSRF-Token": "wrong"}
            )[0]
            == 403,
            "wrong CSRF token is rejected",
        )
        check(
            request("GET", "/api/state", override={"Host": "example.com"})[0] == 403,
            "foreign Host is rejected",
        )
        check(request("GET", "/%2e%2e/server.py")[0] == 400, "path traversal is rejected")
        check(
            request("POST", "/api/demo", {}, authenticated=True)[0] == 409,
            "nonempty demo replacement is refused",
        )
        check(
            request(
                "POST", "/api/import", {"items": [{**item, "quantity": 0}]}, authenticated=True
            )[0]
            == 400,
            "invalid import is rejected",
        )
        check(
            request("GET", "/api/state")[2]["revision"] == state["revision"],
            "rejected requests preserve inventory",
        )
        code, download_headers, exported = request("GET", "/api/export")
        check(
            code == 200 and len(exported) == 10 and "id" not in exported[0],
            "export uses the legacy inventory array",
        )
        check(
            "attachment" in download_headers.get("Content-Disposition", ""), "export is a download"
        )
        changed_id = next(
            i["id"] for i in state["items"] if i["name"] == "Milk" and i["quantity"] == 2
        )
        code, _, removed = request("DELETE", f"/api/items/{changed_id}", authenticated=True)
        check(code == 200 and len(removed["items"]) == 9, "DELETE removes the selected ingredient")
        state = removed
        code, _, imported = request("POST", "/api/import", {"items": exported}, authenticated=True)
        check(
            code == 200 and len(imported["items"]) == 10, "import restores the exported inventory"
        )
        state = imported
        files = list((output / "pantry sessions").glob("demo-*/inventory.json"))
        check(
            len(files) == 1 and json.loads(files[0].read_text(encoding="utf-8")) == exported,
            "saved JSON matches exported inventory",
        )
        for resource in ("index.html", "styles.css", "app.js", "favicon.svg"):
            path = "/" if resource == "index.html" else "/" + resource
            code, _, contents = request("GET", path)
            check(
                code == 200 and contents == (WEB / "static" / resource).read_bytes(),
                f"bundled {resource} matches the source asset",
            )
        packaged = json.loads(diagnostics.read_text(encoding="utf-8"))
        check(packaged["frozen"] is True, "runtime reports a frozen executable")
        check(packaged["tkinter_loaded"] is False, "runtime did not load Tk")
        extraction_root = Path(packaged["resource_root"]).resolve()
        check(
            extraction_root.is_relative_to(temporary.resolve()),
            "onefile resources extract inside isolated verification TEMP",
        )
        for name, path in packaged["module_origins"].items():
            check(
                path is not None and Path(path).resolve().is_relative_to(extraction_root),
                f"{name} loads from the frozen extraction root",
            )
        build_report = json.loads((WEB / "build-report.json").read_text(encoding="utf-8"))
        check(
            Path(packaged["recipe_data_origin"]).resolve().is_relative_to(extraction_root),
            "recipe loader reads data from the frozen extraction root",
        )
        check(
            packaged["recipe_data_sha256"]
            == build_report["application_source_sha256"]["core/genius_kitchen/data/recipes.json"],
            "directly loaded recipe data matches the build input hash",
        )
        check(
            build_report["sha256"] == report["sha256"],
            "verified executable matches the build SHA-256",
        )
        for name, sha256 in packaged["resource_sha256"].items():
            check(
                build_report["application_source_sha256"].get(name) == sha256,
                f"packaged resource hash matches build input: {name}",
            )
        check(
            request("POST", "/api/shutdown", {}, authenticated=True)[0] == 200,
            "authorized HTTP shutdown succeeds",
        )
        stdout, stderr = process.communicate(timeout=10)
        check(process.returncode == 0, "frozen process exits cleanly")
        report.update(
            passed=True,
            exit_code=process.returncode,
            stdout=stdout.decode("utf-8", "replace"),
            stderr=stderr.decode("utf-8", "replace"),
            runtime_diagnostics=str(diagnostics),
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if process.poll() is None and origin and state:
            try:
                state = request("GET", "/api/state")[2]
                request("POST", "/api/shutdown", {}, authenticated=True)
                process.communicate(timeout=5)
            except Exception:
                pass
        if process.poll() is None:
            # Kill only the verifier-created process tree, never another preview.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10
            )
            process.communicate(timeout=5)
        report["check_count"] = len(checks)
        (output / "verification.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        (WEB / "verification/latest.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
