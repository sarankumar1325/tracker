"""Append today's per-target totals from a wheelgap scan to the history file (one entry per day).

    python scripts/update_history.py data/coverage.json data/history.json

The full scan is replaced each night; the history keeps only the small summaries, so the
site can draw coverage over time without the repo growing by a full scan every day.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__:  # imported as scripts.update_history (the tests)
    from . import update_changes
else:  # run as python scripts/update_history.py
    import update_changes

MAX_DAYS = 730  # Keep about two years of nightly scans (one entry per date)


def read_history(path: Path) -> list[dict]:
    """history.json's entries, keeping only well-formed ones, for the publish step.

    Like update_changes.read_changes: a missing file is [], one that isn't valid JSON or isn't a
    list is [] with a warning, and otherwise an entry is kept when it's a dict with a YYYY-MM-DD
    `date` and a dict `summary`, and within the summary only targets whose value is a dict. One
    warning says how many entries and targets were dropped."""
    data, problem = update_changes._read_json_list(path)
    entries: list[dict] = []
    dropped = 0
    for entry in data:
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("date"), str)
            and update_changes.DATE.fullmatch(entry["date"])
            and isinstance(entry.get("summary"), dict)
        ):
            dropped += 1
            continue
        summary = {label: cell for label, cell in entry["summary"].items() if isinstance(cell, dict)}
        dropped += len(entry["summary"]) - len(summary)
        entries.append({**entry, "summary": summary})
    if dropped:
        problem = f"left out {dropped} malformed entr(y/ies) or target(s)"
    update_changes._report(path, problem, strict=False)
    return entries


def update(coverage_path: Path, history_path: Path, max_days: int = MAX_DAYS) -> dict:
    scan = json.loads(coverage_path.read_text(encoding="utf-8"))
    entry = {
        "date": scan["generated"][:10],
        "wheelgap": scan["wheelgap"],
        "packages": len(scan["packages"]),
        "summary": scan["summary"],
    }
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    history = [h for h in history if h["date"] != entry["date"]] + [entry]
    history.sort(key=lambda h: h["date"])
    if len(history) > max_days:
        history = history[-max_days:]
    history_path.write_text(json.dumps(history, separators=(",", ":")) + "\n", encoding="utf-8")
    return entry


if __name__ == "__main__":
    coverage, history = (Path(p) for p in sys.argv[1:3])
    entry = update(coverage, history)
    print(f"history: {entry['date']}, {entry['packages']} packages, {len(entry['summary'])} targets")
