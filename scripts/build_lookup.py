"""Split a wheelgap scan into one small JSON file per package, for scripts and agents.

    python scripts/build_lookup.py data/coverage.json _site/data/packages

Writes <out>/<name>.json for each package (name canonicalised as in PEP 503) and <out>/index.json
listing every package and target. Runs at publish time, so the files are never committed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# A canonical name is also a safe file name: no slashes, dots or leading dashes.
SAFE_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")


def build(coverage_path: Path, out: Path) -> int:
    scan = json.loads(coverage_path.read_text(encoding="utf-8"))
    labels = [t["label"] for t in scan["targets"]]
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for p in scan["packages"]:
        name = canonical(p["name"])
        if not SAFE_NAME.fullmatch(name) or name == "index" or name in index:
            print(f"build_lookup: skipping {p['name']!r}", file=sys.stderr)
            continue
        index[name] = p["version"]
        write_json(out / f"{name}.json", {
            "name": name,
            "version": p["version"],
            "rank": p["rank"],
            "pure": p["pure"],
            "error": p["error"],
            "generated": scan["generated"],
            "wheelgap": scan["wheelgap"],
            "results": dict(zip(labels, p["results"], strict=True)),
        })
    write_json(out / "index.json", {
        "generated": scan["generated"],
        "wheelgap": scan["wheelgap"],
        "targets": scan["targets"],
        "packages": index,
    })
    return len(index)


if __name__ == "__main__":
    coverage, out = (Path(p) for p in sys.argv[1:3])
    print(f"lookup: {build(coverage, out)} packages in {out}")
