"""Record the day a top package's new release drops a platform's wheel (#75).

    python scripts/update_drops.py previous.json data/coverage.json data/drops.json

previous.json is the committed data/coverage.json, copied aside before the scan overwrites it, so a
package's entry there is the release the previous scan saw. When tonight's scan has a new current
release, each target where the previous release had a wheel and the new one builds from source or
has no distribution is a drop: `{date, name, from, version, target}`. Comparing with the previous
scan's release, not a PyPI lookup, compares with the release users had until today; it needs no
network and no extra lookups.

Only real drops count:
- A new release with no wheel on any target yet (its wheels may still be uploading) waits in
  `waiting` and is compared on a later night, against the release before it, once a wheel shows
  up. After WAIT_DAYS with still no wheel at all, it's compared as it is.
- A cell that was or is `unknown` (a failed lookup) isn't compared, nor is a target only one scan has.
- When the current release goes back to an older version, the newer one was yanked (or deleted):
  its drops are removed and it stops waiting.
- A night whose scan used a different wheelgap version is skipped, like scripts/update_changes.py:
  its differences come from wheelgap, not from the packages.

drops.json is `{"schema": 1, "drops": [...], "waiting": [...]}`, drops newest first, for KEEP_DAYS.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

SCHEMA = 1
KEEP_DAYS = 365
WAIT_DAYS = 7
GAP = ("source", "missing")
RELEASE = re.compile(r"(\d+(?:\.\d+)*)")


def release(version: str | None) -> tuple[int, ...] | None:
    """The numeric release segment of a version ("2.0.1rc1" -> (2, 0, 1)), or None if it has none."""
    match = RELEASE.match(version or "")
    if match is None:
        return None
    parts = [int(p) for p in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def went_back(old: str | None, new: str | None) -> bool:
    """Whether the current release moved to an older version: the newer one was yanked or deleted."""
    a, b = release(old), release(new)
    return a is not None and b is not None and b < a


def wheel_targets(package: dict, labels: list[str]) -> list[str]:
    return [label for label, result in zip(labels, package["results"]) if result == "wheel"]


def dropped(wheels: list[str], package: dict, labels: list[str]) -> list[str]:
    """Targets in `wheels` (labels the earlier release had a wheel for) where `package` has none."""
    results = dict(zip(labels, package["results"]))
    return [label for label in wheels if results.get(label) in GAP]


def compare(old: dict, new: dict, state: dict, today: str) -> list[dict]:
    """Fold tonight's scan into `state` (drops and waiting) and return the new drops."""
    old_labels = [t["label"] for t in old.get("targets", [])]
    new_labels = [t["label"] for t in new["targets"]]
    shared = [label for label in new_labels if label in old_labels]
    old_packages = {p["name"]: p for p in old.get("packages", [])}
    waiting = {w["name"]: w for w in state["waiting"]}
    found: list[dict] = []

    def record(name: str, frm: str, version: str, targets: list[str]) -> None:
        found.extend({"date": today, "name": name, "from": frm, "version": version, "target": t} for t in targets)

    for pkg in new["packages"]:
        name, version = pkg["name"], pkg["version"]
        if pkg.get("error") or not version:
            continue
        wait = waiting.get(name)
        if wait is not None:
            if version == wait["from"] or went_back(wait["version"], version):
                del waiting[name]  # the waiting release was yanked
                state["drops"] = [d for d in state["drops"] if not (d["name"] == name and d["version"] == wait["version"])]
                continue
            expired = date.fromisoformat(today) - date.fromisoformat(wait["since"]) >= timedelta(days=WAIT_DAYS)
            if wheel_targets(pkg, new_labels) or expired:
                del waiting[name]
                record(name, wait["from"], version, dropped(wait["wheels"], pkg, new_labels))
            else:
                wait["version"] = version
            continue
        before = old_packages.get(name)
        if before is None or before.get("error") or not before["version"] or before["version"] == version:
            continue
        if went_back(before["version"], version):
            # The newer release was yanked or deleted: whatever it dropped doesn't count.
            gone = before["version"]
            state["drops"] = [d for d in state["drops"] if not (d["name"] == name and d["version"] == gone)]
            continue
        old_results = dict(zip(old_labels, before["results"]))
        wheels = [label for label in shared if old_results[label] == "wheel"]
        if not wheels:
            continue
        if not wheel_targets(pkg, new_labels):
            # No wheel anywhere yet: maybe still uploading. Look again on a later night.
            waiting[name] = {"name": name, "from": before["version"], "version": version, "wheels": wheels,
                             "since": today}
            continue
        record(name, before["version"], version, dropped(wheels, pkg, new_labels))
    state["waiting"] = sorted(waiting.values(), key=lambda w: w["name"])
    return found


def load(path: Path) -> dict:
    if not path.exists():
        return {"schema": SCHEMA, "drops": [], "waiting": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        sys.exit(f"update_drops: {path} schema {data.get('schema')!r}, expected {SCHEMA}")
    return data


def update(previous_path: Path, coverage_path: Path, drops_path: Path) -> list[dict] | str:
    """Record tonight's drops and return them, or return why nothing was compared."""
    new = json.loads(coverage_path.read_text(encoding="utf-8"))
    state = load(drops_path)
    old = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else None
    if old is None:
        return f"no {previous_path}, nothing to compare"
    if old.get("wheelgap") != new.get("wheelgap"):
        return f"wheelgap {old.get('wheelgap')} -> {new.get('wheelgap')}, so differences aren't the packages'"
    today = new["generated"][:10]
    found = compare(old, new, state, today)
    seen = {(d["name"], d["version"], d["target"]) for d in state["drops"]}
    fresh = [d for d in found if (d["name"], d["version"], d["target"]) not in seen]  # a second scan the same day
    cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS - 1)).isoformat()
    state["drops"] = [d for d in fresh + state["drops"] if d["date"] >= cutoff]
    state["drops"].sort(key=lambda d: d["date"], reverse=True)  # stable: tonight's in scan (rank) order
    drops_path.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    return fresh


if __name__ == "__main__":
    previous, coverage, drops = (Path(p) for p in sys.argv[1:4])
    result = update(previous, coverage, drops)
    if isinstance(result, str):
        print(f"drops: nothing recorded ({result})")
    else:
        print(f"drops: {len(result)} new")
