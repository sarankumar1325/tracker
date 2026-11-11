"""Refuse notes that don't match the v0 format, before they reach the knowledge base.

    python3 scripts/check_notes.py [notes_dir] [coverage.json]

Standard library only. Exit 0 when every file in notes_dir (except README.md)
is a valid notes/<normalized-name>.toml. Print one problem per line otherwise.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import tomllib
from pathlib import Path

KINDS = ("workaround", "alternative", "upstream-issue", "other-source")
MAX_TEXT = 500
NAME_RE = re.compile(r"[-_.]+")


def normalize_name(name: str) -> str:
    """PEP 503 normalization: lowercase, runs of -, _ and . become one -."""
    return NAME_RE.sub("-", name).lower()


def platform_names(coverage: dict) -> set[str]:
    names: set[str] = set()
    for target in coverage.get("targets", []):
        if platform := target.get("platform"):
            names.add(platform)
    return names


def problems(notes_dir: Path, coverage: dict) -> list[str]:
    allowed = platform_names(coverage)
    if not allowed:
        return ["coverage has no target platforms"]

    out: list[str] = []
    paths = sorted(
        p for p in notes_dir.iterdir() if p.is_file() and p.name != "README.md"
    )
    for path in paths:
        out.extend(_file_problems(path, notes_dir, allowed))
    return out


def _file_problems(path: Path, notes_dir: Path, allowed: set[str]) -> list[str]:
    rel = path.relative_to(notes_dir).as_posix() if path.is_relative_to(notes_dir) else path.name
    if path.suffix != ".toml":
        return [f"{rel}: not a .toml file"]
    stem = path.stem
    if normalize_name(stem) != stem or not stem:
        return [f"{rel}: filename must be the normalized package name (got {stem!r})"]

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return [f"{rel}: {e}"]

    notes = data.get("note")
    if not isinstance(notes, list) or not notes:
        return [f"{rel}: needs at least one [[note]]"]

    out: list[str] = []
    for i, note in enumerate(notes, start=1):
        prefix = f"{rel} note {i}"
        if not isinstance(note, dict):
            out.append(f"{prefix}: expected a table")
            continue
        out.extend(_note_problems(prefix, note, allowed))
    return out


def _note_problems(prefix: str, note: dict, allowed: set[str]) -> list[str]:
    out: list[str] = []
    platforms = note.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        out.append(f"{prefix}: platforms must be a non-empty list")
    else:
        if platforms == ["all"]:
            pass
        else:
            for p in platforms:
                if not isinstance(p, str) or p == "all" or p not in allowed:
                    out.append(f"{prefix}: unknown platform {p!r}")
                    break

    kind = note.get("kind")
    if kind not in KINDS:
        out.append(f"{prefix}: kind must be one of {', '.join(KINDS)}")

    text = note.get("text")
    if not isinstance(text, str) or not text.strip():
        out.append(f"{prefix}: text must be a non-empty string")
    elif len(text) > MAX_TEXT:
        out.append(f"{prefix}: text is {len(text)} characters, limit is {MAX_TEXT}")

    links = note.get("links")
    if not isinstance(links, list) or not links:
        out.append(f"{prefix}: links must be a non-empty list")
    else:
        for link in links:
            if not isinstance(link, str) or not link.startswith("https://"):
                out.append(f"{prefix}: links must be https URLs (got {link!r})")
                break

    if "versions" in note and (
        not isinstance(note["versions"], str) or not note["versions"].strip()
    ):
        out.append(f"{prefix}: versions must be a non-empty string when set")

    updated = note.get("updated")
    if not isinstance(updated, dt.date):
        out.append(f"{prefix}: updated must be a date")

    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent
    notes_dir = Path(args[0]) if args else root / "notes"
    coverage_path = Path(args[1]) if len(args) > 1 else root / "data" / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    found = problems(notes_dir, coverage)
    if found:
        print("\n".join(found), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
