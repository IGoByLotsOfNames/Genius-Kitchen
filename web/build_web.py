"""Build the local Genius Kitchen browser application as a Windows executable."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WEB = Path(__file__).resolve().parent
DESKTOP = WEB.parent / "desktop"
WORKING = WEB.parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-dir", type=Path, default=DESKTOP / "tools")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.version_info < (3, 11):
        parser.error("Build using Windows Python 3.11 or newer")
    tools = args.tools_dir.resolve()
    if not (tools / "PyInstaller").is_dir():
        parser.error(f"Pinned PyInstaller tools are missing: {tools}")
    for name in (
        "server.py",
        "demo_sample.json",
        "static/index.html",
        "static/styles.css",
        "static/app.js",
        "static/favicon.svg",
        "core/genius_kitchen/recipes.py",
    ):
        if not (WEB / name).is_file():
            parser.error(f"Required build input is missing: {name}")
    build = WEB / "build"
    for path in (build / "tmp", build / "cache", build / "spec", WEB / "dist", WEB / "assets"):
        path.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "TCL_LIBRARY", "TK_LIBRARY"):
        environment.pop(name, None)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(tools),
            "TEMP": str(build / "tmp"),
            "TMP": str(build / "tmp"),
            "PYINSTALLER_CONFIG_DIR": str(build / "cache"),
        }
    )
    inputs = [WEB / "server.py", WEB / "demo_sample.json"]
    inputs += sorted(
        p for p in (WEB / "core").rglob("*") if p.is_file() and p.suffix in {".py", ".json"}
    )
    inputs += sorted(p for p in (WEB / "static").rglob("*") if p.is_file())
    hashes = {p.relative_to(WEB).as_posix(): digest(p) for p in inputs}
    versions = {}
    for entry in tools.glob("*.dist-info"):
        name, _, version = entry.name.removesuffix(".dist-info").rpartition("-")
        if name and version:
            versions[name.lower().replace("_", "-")] = version
    pinned = {}
    for line in (WEB / "requirements-build.txt").read_text(encoding="utf-8").splitlines():
        if "==" in line and not line.startswith("#"):
            name, version = line.strip().split("==", 1)
            pinned[name] = version
    if any(versions.get(name) != version for name, version in pinned.items()):
        raise RuntimeError(
            "Installed tool metadata directory versions do not match the pinned toolchain"
        )
    info = {
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "builder_versions_from_metadata_directories": versions,
        "pinned_build_requirements": pinned,
        "application_source_sha256": hashes,
        "build_script_sha256": digest(Path(__file__)),
        "scope": "Local loopback web application",
    }
    info_path = WEB / "assets/build-info.json"
    info_path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        "-B",
        "-m",
        "PyInstaller",
        str(WEB / "server.py"),
        "--name=GeniusKitchen-Web",
        "--onefile",
        "--windowed",
        "--noupx",
        f"--paths={WEB / 'core'}",
        f"--add-data={WEB / 'core'};core",
        f"--add-data={WEB / 'core/genius_kitchen/data/recipes.json'};genius_kitchen/data",
        f"--add-data={WEB / 'static'};static",
        f"--add-data={WEB / 'demo_sample.json'};.",
        f"--add-data={info_path};assets",
        "--exclude-module=tkinter",
        "--exclude-module=_tkinter",
        f"--distpath={WEB / 'dist'}",
        f"--workpath={build / 'work'}",
        f"--specpath={build / 'spec'}",
        "--clean",
        "--noconfirm",
    ]
    icon = DESKTOP / "assets/GeniusKitchen.ico"
    if icon.is_file():
        copied_icon = WEB / "assets/GeniusKitchen.ico"
        shutil.copyfile(icon, copied_icon)
        command.append(f"--icon={copied_icon}")
    with (build / "build.log").open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            command, cwd=WEB, env=environment, text=True, stdout=stream, stderr=subprocess.STDOUT
        )
    if result.returncode:
        print(f"Build failed ({result.returncode}); see {build / 'build.log'}")
        return result.returncode
    changed = [name for name, expected in hashes.items() if digest(WEB / name) != expected]
    if changed:
        raise RuntimeError(
            f"Inputs changed during the build; rebuild after changes settle: {changed}"
        )
    executable = WEB / "dist/GeniusKitchen-Web.exe"
    shutil.copyfile(WORKING / "LICENSE", WEB / "dist/LICENSE.txt")
    report = {
        **info,
        "build_exit_code": 0,
        "application_inputs_unchanged": True,
        "executable": executable.relative_to(WEB).as_posix(),
        "bytes": executable.stat().st_size,
        "sha256": digest(executable),
        "command": command,
        "unsigned": True,
        "external_python_home_removed": True,
        "tkinter_explicitly_excluded": True,
    }
    (WEB / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"executable": str(executable), "bytes": report["bytes"], "sha256": report["sha256"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
