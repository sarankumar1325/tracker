"""Record the day a top package's new release drops a platform's wheel (#75).

    python scripts/update_drops.py previous.json data/coverage.json data/drops.json

previous.json is the committed data/coverage.json, copied aside before the scan overwrites it, so a
package's entry there is the release the previous scan saw. When tonight's scan has a new current
release, each target where the previous release had a wheel and the new one builds from source or
has no distribution is a candidate drop. Comparing with the previous scan's release, not a PyPI
lookup, compares with the release users had until today; it needs no network and no extra lookups.

A candidate is never published the night it's first seen: a release's wheels are often uploaded by
several CI jobs, so a scan can catch the Linux wheels up and the Windows or macOS ones still on their
way. Every candidate waits in `waiting` with the scan that first saw it (`since`), and is published
as a drop `{date, name, from, version, target}` only if a later scan, HOLD_HOURS or more after that,
still finds the same release without the wheel. Wheels that show up in between take their targets
off the candidates. So a drop is listed the night it's confirmed, usually the night after the
release.

Only real drops count:
- A release with no wheel on any target yet (all its wheels may still be uploading) waits until a
  wheel shows up, or as it is after WAIT_DAYS.
- When no target of one Python has a wheel any more but other Pythons still do, the release ended
  support for that Python (the scan reads wheel tags, not Requires-Python, so it can't tell): its
  targets aren't listed as dropped platforms.
- A cell that was or is `unknown` (a failed lookup) isn't compared, nor is a target only one scan
  has, nor one whose definition (python, platform, glibc, musl, macos, ...) or, for Pyodide, whose
  Pyodide lock changed between the two scans.
- When the current release goes back to an older version, the newer one was yanked (or deleted):
  its drops are removed and it stops waiting. A newer release while one waits replaces it, held
  from that night on the targets still held, still compared with the release users had before.
- A night whose scan used a different wheelgap version is skipped, like scripts/update_changes.py:
  its differences come from wheelgap, not from the packages. Waiting releases are cleared then, so
  they're never compared across wheelgap versions; drops.json keeps the version it waited under.
- A package that leaves the scan (the top N) stops waiting.

drops.json is `{"schema": 1, "wheelgap", "drops": [...], "waiting": [...]}`, drops newest first, for
KEEP_DAYS. A waiting entry is `{name, from, version, targets, since}`: `targets` are the candidate
drops and `since` is the `generated` time of the scan that first saw `version`.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA = 1
KEEP_DAYS = 365
WAIT_DAYS = 7
HOLD_HOURS = 20  # nightly scans are about 24 hours apart; a second scan the same night is not "later"
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


def pyodide_locks(scan: dict) -> dict[str, dict] | None:
    """Python -> the scan's pyodide_locks entry, or None if the list is malformed."""
    locks = scan.get("pyodide_locks", [])
    if not isinstance(locks, list) or not all(isinstance(lock, dict) for lock in locks):
        return None
    return {str(lock.get("python")): lock for lock in locks}


def shared_labels(old: dict, new: dict) -> list[str]:
    """Labels in both scans that mean the same target: an equal target definition and, for a Pyodide
    target, the same Pyodide lock for its Python. In tonight's target order."""
    old_targets = {t["label"]: t for t in old.get("targets", [])}
    old_locks, new_locks = pyodide_locks(old), pyodide_locks(new)
    out = []
    for target in new["targets"]:
        if old_targets.get(target["label"]) != target:
            continue
        if target.get("platform") == "pyodide":
            if old_locks is None or new_locks is None:
                continue
            python = str(target.get("python"))
            if old_locks.get(python) != new_locks.get(python):
                continue
        out.append(target["label"])
    return out


def dropped(targets: list[str], package: dict, labels: list[str]) -> list[str]:
    """Targets in `targets` (labels an earlier release had a wheel for) where `package` has none."""
    results = dict(zip(labels, package["results"]))
    return [label for label in targets if results.get(label) in GAP]


def python_dropped(targets: list[str], package: dict, new_targets: list[dict]) -> list[str]:
    """`targets` minus those of a Python the release ended support for: no target of that Python has a
    wheel tonight while a target of another Python does. A release dropping Python 3.13 turns every
    3.13 target from wheel to source at once, which isn't a platform being dropped."""
    python_of = {t["label"]: str(t.get("python")) for t in new_targets}
    with_wheel = {python_of[t["label"]] for t, result in zip(new_targets, package["results"]) if result == "wheel"}
    if not with_wheel:
        return targets  # no wheel anywhere: not a Python ending, see WAIT_DAYS
    return [label for label in targets if python_of.get(label) in with_wheel]


def hours_between(since: str, now: str) -> float:
    return (datetime.fromisoformat(now) - datetime.fromisoformat(since)).total_seconds() / 3600


def compare(old: dict, new: dict, state: dict) -> list[dict]:
    """Fold tonight's scan into `state` (drops and waiting) and return the newly confirmed drops."""
    now = new["generated"]
    today = now[:10]
    new_labels = [t["label"] for t in new["targets"]]
    shared = shared_labels(old, new)
    old_labels = [t["label"] for t in old.get("targets", [])]
    old_packages = {p["name"]: p for p in old.get("packages", [])}
    tonight = {p["name"] for p in new["packages"]}
    # A package that left the scan (the top N) stops waiting: there's no later scan of it to confirm with.
    waiting = {w["name"]: w for w in state["waiting"] if w["name"] in tonight}
    found: list[dict] = []

    def record(name: str, frm: str, version: str, targets: list[str]) -> None:
        found.extend({"date": today, "name": name, "from": frm, "version": version, "target": t} for t in targets)

    def hold(name: str, frm: str, version: str, targets: list[str], since: str) -> None:
        if targets:
            waiting[name] = {"name": name, "from": frm, "version": version, "targets": targets, "since": since}
        else:
            waiting.pop(name, None)

    for pkg in new["packages"]:
        name, version = pkg["name"], pkg["version"]
        if pkg.get("error") or not version:
            continue  # nothing to compare tonight; a waiting release keeps waiting
        # A wheel that arrived after its drop was published (a late upload): that drop wasn't real, so withdraw it.
        results = dict(zip(new_labels, pkg["results"]))
        state["drops"] = [d for d in state["drops"]
                          if not (d["name"] == name and d["version"] == version and results.get(d["target"]) == "wheel")]
        wait = waiting.get(name)
        if wait is not None:
            if version == wait["from"] or went_back(wait["version"], version):
                del waiting[name]  # the waiting release was yanked
                state["drops"] = [d for d in state["drops"] if not (d["name"] == name and d["version"] == wait["version"])]
                continue
            # Keep only targets that mean the same thing tonight as in every scan since the candidate was seen.
            candidates = dropped([t for t in wait["targets"] if t in shared], pkg, new_labels)
            if version != wait["version"]:
                # A newer release before this one was confirmed: hold it in its place from tonight, on the
                # targets still held, compared with the release users had before (`from`).
                hold(name, wait["from"], version, candidates, now)
                continue
            if not candidates:
                del waiting[name]  # the missing wheels were uploaded: no drop
                continue
            first_seen = wait["since"]
            if hours_between(first_seen, now) < HOLD_HOURS:
                hold(name, wait["from"], version, candidates, first_seen)  # the same night: not later yet
                continue
            expired = date.fromisoformat(today) - date.fromisoformat(first_seen[:10]) >= timedelta(days=WAIT_DAYS)
            if "wheel" not in pkg["results"] and not expired:
                hold(name, wait["from"], version, candidates, first_seen)  # no wheel anywhere yet
                continue
            del waiting[name]
            record(name, wait["from"], version, python_dropped(candidates, pkg, new["targets"]))
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
        wheels = [label for label in shared if old_results.get(label) == "wheel"]
        # Never published the night it's first seen: its other wheels may still be uploading.
        hold(name, before["version"], version, dropped(wheels, pkg, new_labels), now)
    state["waiting"] = sorted(waiting.values(), key=lambda w: w["name"])
    return found


def load(path: Path) -> dict:
    if not path.exists():
        return {"schema": SCHEMA, "wheelgap": None, "drops": [], "waiting": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        sys.exit(f"update_drops: {path} schema {data.get('schema')!r}, expected {SCHEMA}")
    return data


def save(state: dict, path: Path) -> None:
    out = {"schema": SCHEMA, "wheelgap": state.get("wheelgap"), "drops": state["drops"], "waiting": state["waiting"]}
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


def update(previous_path: Path, coverage_path: Path, drops_path: Path) -> list[dict] | str:
    """Record tonight's drops and return them, or return why nothing was compared."""
    new = json.loads(coverage_path.read_text(encoding="utf-8"))
    state = load(drops_path)
    old = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else None
    if old is None:
        return f"no {previous_path}, nothing to compare"
    if state.get("wheelgap") != new.get("wheelgap"):
        # Held under another wheelgap version (even if a night in between wasn't recorded): its results
        # aren't comparable with tonight's.
        state["waiting"] = []
        state["wheelgap"] = new.get("wheelgap")
    if old.get("wheelgap") != new.get("wheelgap"):
        save(state, drops_path)
        return f"wheelgap {old.get('wheelgap')} -> {new.get('wheelgap')}, so differences aren't the packages'"
    today = new["generated"][:10]
    found = compare(old, new, state)
    seen = {(d["name"], d["version"], d["target"]) for d in state["drops"]}
    fresh = [d for d in found if (d["name"], d["version"], d["target"]) not in seen]
    cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS - 1)).isoformat()
    state["drops"] = [d for d in fresh + state["drops"] if d["date"] >= cutoff]
    state["drops"].sort(key=lambda d: d["date"], reverse=True)  # stable: tonight's in scan (rank) order
    save(state, drops_path)
    return fresh


if __name__ == "__main__":
    previous, coverage, drops = (Path(p) for p in sys.argv[1:4])
    result = update(previous, coverage, drops)
    if isinstance(result, str):
        print(f"drops: nothing recorded ({result})")
    else:
        print(f"drops: {len(result)} new")
