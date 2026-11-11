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
MAX_TEXT = 500  # text must be shorter than this
NOTE_KEYS = frozenset({"platforms", "kind", "text", "links", "versions", "updated"})
NAME_RE = re.compile(r"[-_.]+")
STEM_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# One PEP 440 specifier clause; versions is one or more of these, comma-separated.
SPEC_CLAUSE_RE = re.compile(r"\s*(~=|===|==|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+\s*")


def normalize_name(name: str) -> str:
    """PEP 503 normalization: lowercase, runs of -, _ and . become one -."""
    return NAME_RE.sub("-", name).lower()


def valid_specifier(value: object) -> bool:
    """A comma-separated list of PEP 440 clauses, like "<3" or ">=2.8, <2.10"."""
    if not isinstance(value, str) or not value.strip():
        return False
    return all(SPEC_CLAUSE_RE.fullmatch(clause) for clause in value.split(","))


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
    rel = (
        path.relative_to(notes_dir).as_posix()
        if path.is_relative_to(notes_dir)
        else path.name
    )
    if path.suffix != ".toml":
        return [f"{rel}: not a .toml file"]
    stem = path.stem
    if not STEM_RE.fullmatch(stem):
        return [f"{rel}: filename must be the normalized package name (got {stem!r})"]

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return [f"{rel}: not valid UTF-8"]
    except (OSError, tomllib.TOMLDecodeError) as e:
        return [f"{rel}: {e}"]

    out: list[str] = []
    unknown = sorted(set(data) - {"note"})
    if unknown:
        out.append(f"{rel}: unknown top-level keys: {', '.join(unknown)}")

    notes = data.get("note")
    if not isinstance(notes, list) or not notes:
        out.append(f"{rel}: needs at least one [[note]]")
        return out

    for i, note in enumerate(notes, start=1):
        prefix = f"{rel} note {i}"
        if not isinstance(note, dict):
            out.append(f"{prefix}: expected a table")
            continue
        out.extend(_note_problems(prefix, note, allowed))
    return out


def _note_problems(prefix: str, note: dict, allowed: set[str]) -> list[str]:
    out: list[str] = []
    unknown = sorted(set(note) - NOTE_KEYS)
    if unknown:
        out.append(f"{prefix}: unknown keys: {', '.join(unknown)}")

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
    elif len(text) >= MAX_TEXT:
        out.append(
            f"{prefix}: text is {len(text)} characters, must be under {MAX_TEXT}"
        )

    links = note.get("links")
    if not isinstance(links, list) or not links:
        out.append(f"{prefix}: links must be a non-empty list")
    else:
        for link in links:
            if not isinstance(link, str) or not link.startswith("https://"):
                out.append(f"{prefix}: links must be https URLs (got {link!r})")
                break

    if "versions" in note and not valid_specifier(note["versions"]):
        out.append(
            f'{prefix}: versions must be a PEP 440 specifier such as "<3" '
            f"(got {note['versions']!r})"
        )

    # A TOML datetime is a dt.datetime, which subclasses dt.date: require a bare date.
    if type(note.get("updated")) is not dt.date:
        out.append(
            f"{prefix}: updated must be a date like 2026-11-11, not a string or datetime"
        )

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
