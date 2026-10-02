"""Keep the browser's packaged core exactly aligned with the desktop core."""

from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "src/genius_kitchen"
    copied = root / "web/core/genius_kitchen"
    names = {
        p.relative_to(source).as_posix()
        for p in source.rglob("*")
        if p.is_file() and p.suffix in {".py", ".json"}
    }
    copied_names = {
        p.relative_to(copied).as_posix()
        for p in copied.rglob("*")
        if p.is_file() and p.suffix in {".py", ".json"}
    }
    if names != copied_names:
        raise SystemExit(f"Core file sets differ: {sorted(names ^ copied_names)}")
    different = [
        name for name in sorted(names)
        if (source / name).read_bytes() != (copied / name).read_bytes()
    ]
    if different:
        raise SystemExit(f"Core copies differ: {different}")
    print(f"All {len(names)} browser core files match the desktop source byte-for-byte.")


if __name__ == "__main__":
    main()
