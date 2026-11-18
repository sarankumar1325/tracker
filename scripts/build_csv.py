"""Write the scan as a CSV for spreadsheets and notebooks.

    python scripts/build_csv.py data/coverage.json _site/data/coverage.csv
    python scripts/build_csv.py data/coverage.json _site/data/coverage.csv --history data/history.json _site/data/history.csv

Writes one row per package: rank, name, version, downloads, pure, error, then one
column per target, named by its label, holding wheel/bundled/source/missing/unknown/n/a.
Runs at publish time, so the file is never committed.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

SCAN_SCHEMA = 1  # of the coverage.json this reads


def cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def build(coverage_path: Path, out: Path) -> int:
    scan = json.loads(coverage_path.read_text(encoding="utf-8"))
    if scan.get("schema") != SCAN_SCHEMA:
        sys.exit(f"build_csv: coverage.json schema {scan.get('schema')!r}, expected {SCAN_SCHEMA}")
    labels = [t["label"] for t in scan["targets"]]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rank", "name", "version", "downloads", "pure", "error", *labels])
        for package in scan["packages"]:
            writer.writerow(
                [
                    cell(package["rank"]),
                    package["name"],
                    cell(package.get("version")),
                    cell(package.get("downloads")),
                    cell(package.get("pure")),
                    cell(package.get("error")),
                    *package["results"],
                ]
            )
    return len(scan["packages"])


def nonnegative_count(value: object) -> int | None:
    if type(value) is int and value >= 0:
        return value
    if type(value) is float and value >= 0 and value.is_integer():
        return int(value)
    return None


def build_history(history_path: Path, out: Path) -> int:
    """Write one coverage row per chartable night and target."""
    history = json.loads(history_path.read_text(encoding="utf-8"))
    entries = [entry for entry in history if isinstance(entry, dict)] if isinstance(history, list) else []
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "date", "wheelgap", "packages", "target", "python", "platform",
            "wheel", "bundled", "source", "missing", "unknown", "share",
        ])
        for entry in sorted(entries, key=lambda night: str(night.get("date", ""))):
            packages = nonnegative_count(entry.get("packages"))
            summary = entry.get("summary")
            if not packages or not isinstance(summary, dict):
                continue
            for target, counts in summary.items():
                if not isinstance(counts, dict):
                    continue
                wheel = nonnegative_count(counts.get("wheel"))
                if wheel is None:
                    continue
                bundled, source, missing, unknown = (
                    nonnegative_count(counts.get(key)) or 0 for key in ("bundled", "source", "missing", "unknown")
                )
                python, _, platform = target.partition(" ")
                wheelgap = entry.get("wheelgap")
                # Match the chart's Number.toFixed(1), including exact half-step ties.
                share = Decimal(100 * (wheel + bundled) / packages).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
                writer.writerow([
                    entry.get("date", ""), wheelgap if isinstance(wheelgap, str) else "", packages, target,
                    python, platform, wheel, bundled, source, missing, unknown, share,
                ])
                rows += 1
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--history", nargs=2, type=Path, metavar=("HISTORY_JSON", "HISTORY_CSV"))
    args = parser.parse_args()
    print(f"csv: {build(args.coverage, args.out)} packages in {args.out}")
    if args.history:
        history, history_out = args.history
        print(f"history csv: {build_history(history, history_out)} rows in {history_out}")
