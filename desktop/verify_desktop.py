"""Run the actual EXE with a fresh pantry and hidden Tk; never open personal data."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent


def main() -> int:
    executable = DESKTOP / "dist/GeniusKitchen-Desktop.exe"
    if not executable.is_file():
        raise FileNotFoundError("Build GeniusKitchen-Desktop.exe before running verification")
    unique = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = DESKTOP / "verification" / unique
    output.mkdir(parents=True, exist_ok=False)
    temporary = output / "temporary"
    temporary.mkdir()
    data_dir = output / "pantry"
    report_path = output / "packaged-smoke.json"
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "TCL_LIBRARY", "TK_LIBRARY"):
        environment.pop(name, None)
    environment.update(TEMP=str(temporary), TMP=str(temporary), PYTHONDONTWRITEBYTECODE="1")
    command = [
        str(executable),
        "--smoke-test",
        "--data-dir",
        str(data_dir),
        "--report",
        str(report_path),
    ]
    try:
        result = subprocess.run(
            command,
            cwd=output,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        report = (
            json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
        )
        passed = bool(result.returncode == 0 and report and report["passed"] and report["frozen"])
        summary = {
            "passed": passed,
            "executable": str(executable),
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "exit_code": result.returncode,
            "report": str(report_path),
            "external_python_and_tcl_environment_removed": True,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        summary = {"passed": False, "reason": "packaged smoke test exceeded 90 seconds"}
        passed = False
    (output / "verification.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (DESKTOP / "verification/latest.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
