"""Build the current working copy into a Windows EXE without modifying its files."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent
WORKING = DESKTOP.parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-dir", type=Path, default=DESKTOP / "tools")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Build the Windows executable using Windows Python")
    if sys.version_info < (3, 11):
        parser.error("Python 3.11+ is required")
    required = [
        WORKING / "src/genius_kitchen/app.py",
        WORKING / "demo.py",
        WORKING / "demo/pantry.json",
    ]
    for source in required:
        if not source.is_file():
            parser.error(f"Working-copy input is missing: {source}")
    assets = DESKTOP / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    build = DESKTOP / "build"
    for directory in (build, build / "tmp", build / "cache", build / "spec", DESKTOP / "dist"):
        directory.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEMP": str(build / "tmp"),
            "TMP": str(build / "tmp"),
            "PYINSTALLER_CONFIG_DIR": str(build / "cache"),
            "PYTHONPATH": str(args.tools_dir.resolve()) if args.tools_dir.is_dir() else "",
        }
    )
    # Portable Python distributions sometimes need their existing Tcl scripts located explicitly.
    import _tkinter

    for name, version, marker in (
        ("TCL_LIBRARY", _tkinter.TCL_VERSION, "init.tcl"),
        ("TK_LIBRARY", _tkinter.TK_VERSION, "tk.tcl"),
    ):
        folder = "tcl" if name == "TCL_LIBRARY" else "tk"
        candidate = Path(sys.base_prefix) / "tcl" / f"{folder}{version}"
        if name not in env and (candidate / marker).is_file():
            env[name] = str(candidate)

    versions = {}
    # The preinstalled tool directory may omit METADATA while retaining versioned dist-info folders.
    local_versions = {}
    for metadata_dir in args.tools_dir.glob("*.dist-info"):
        name, _, version = metadata_dir.name.removesuffix(".dist-info").rpartition("-")
        if name and version:
            local_versions[name.lower().replace("_", "-")] = version
    for name in (
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "setuptools",
        "altgraph",
        "packaging",
        "pefile",
        "pywin32-ctypes",
    ):
        try:
            versions[name] = (
                local_versions[name] if name in local_versions else importlib.metadata.version(name)
            )
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not found in builder metadata"
    inputs = sorted((WORKING / "src/genius_kitchen").rglob("*.py"))
    inputs += [
        WORKING / "src/genius_kitchen/data/recipes.json",
        WORKING / "demo.py",
        WORKING / "demo/pantry.json",
    ]
    source_hashes = {
        str(path.relative_to(WORKING)).replace("\\", "/"): digest(path) for path in inputs
    }
    build_info = {
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "builder_versions": versions,
        "application_source_sha256": source_hashes,
        "launcher_sha256": digest(DESKTOP / "launcher.py"),
        "scope": "Current working-copy Tk app, not the historical native-Windows reconstruction",
    }
    (assets / "build-info.json").write_text(
        json.dumps(build_info, indent=2) + "\n", encoding="utf-8"
    )
    command = [
        sys.executable,
        "-B",
        "-m",
        "PyInstaller",
        str(DESKTOP / "launcher.py"),
        "--name=GeniusKitchen-Desktop",
        "--onefile",
        "--windowed",
        "--noupx",
        f"--paths={WORKING / 'src'}",
        f"--paths={WORKING}",
        f"--add-data={WORKING / 'src/genius_kitchen/data/recipes.json'};genius_kitchen/data",
        f"--add-data={WORKING / 'demo/pantry.json'};demo",
        f"--add-data={assets / 'build-info.json'};assets",
        f"--distpath={DESKTOP / 'dist'}",
        f"--workpath={build / 'work'}",
        f"--specpath={build / 'spec'}",
        "--clean",
        "--noconfirm",
    ]
    icon = assets / "GeniusKitchen.ico"
    if icon.is_file():
        command.extend([f"--icon={icon}", f"--add-data={icon};assets"])
    with (build / "build.log").open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            command, cwd=DESKTOP, env=env, text=True, stdout=stream, stderr=subprocess.STDOUT
        )
    if result.returncode:
        print(f"Build failed ({result.returncode}); inspect {build / 'build.log'}")
        return result.returncode
    changed = [
        name for name, expected in source_hashes.items() if digest(WORKING / name) != expected
    ]
    if changed:
        raise RuntimeError(f"Source changed during build; rebuild after changes settle: {changed}")
    executable = DESKTOP / "dist/GeniusKitchen-Desktop.exe"
    shutil.copyfile(WORKING / "LICENSE", DESKTOP / "dist/LICENSE.txt")
    result_report = {
        **build_info,
        "build_exit_code": result.returncode,
        "executable": str(executable.relative_to(DESKTOP)),
        "bytes": executable.stat().st_size,
        "sha256": digest(executable),
        "application_inputs_unchanged": True,
        "command": command,
        "unsigned": True,
    }
    (DESKTOP / "build-report.json").write_text(
        json.dumps(result_report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "executable": str(executable),
                "bytes": executable.stat().st_size,
                "sha256": result_report["sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
