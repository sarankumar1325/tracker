"""Whole-tree install results (`install` in the package JSON, from scan_install.py), as build_pages.py and
build_badges.py read them: which results count as checked, and which Python a summary of them is for.

Stdlib only, like the other scripts.
"""

from __future__ import annotations

CHECKED = ("wheel", "source", "missing")  # an install result that was checked; `not_checked` isn't


def python_key(value: str) -> tuple[int, int]:
    major, minor = value.rstrip("t").split(".", 1)
    return int(major), int(minor)


def native_install(package: dict, targets: list[dict]) -> list[tuple[dict, dict]]:
    """(target, result) for each of the package's install results on a native target: a target in the scan,
    not free-threaded and not Pyodide. A result that isn't an object reads as {} (not checked)."""
    by_label = {t["label"]: t for t in targets}
    install = package.get("install")
    if not isinstance(install, dict):
        return []
    found = []
    for label, result in install.items():
        target = by_label.get(label)
        if target is None or str(target["python"]).endswith("t") or target["platform"] == "pyodide":
            continue
        found.append((target, result if isinstance(result, dict) else {}))
    return found


def install_python(package: dict, targets: list[dict]) -> str | None:
    """The newest non-free-threaded Python with a checked native install result, or None without one.

    It can be older than the newest Python in the scan: install coverage is only scanned for some Pythons,
    and a Python whose install results are all `not_checked` has nothing to report."""
    pythons = {t["python"] for t, result in native_install(package, targets) if result.get("status") in CHECKED}
    return max(pythons, key=python_key) if pythons else None
