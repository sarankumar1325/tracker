"""Build a static HTML page per package from a wheelgap coverage scan, plus a sitemap.

    python scripts/build_pages.py data/coverage.json _site

Writes <site>/p/<name>/index.html for each package (PEP 503 canonical name) and
<site>/sitemap.xml listing the main page and every package page. Runs at publish
time; the files are not committed. The pages are plain HTML (no JavaScript) and
reuse site/style.css, so search engines can find "does <package> have ARM wheels".
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

SCAN_SCHEMA = 1
SAFE_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
BASE_URL = "https://wheelgap.github.io/tracker/"

# Same order and names as PLATFORM_NAMES in site/app.js.
PLATFORM_NAMES = {
    "linux-x86_64": "Linux x86_64",
    "linux-aarch64": "Linux ARM64",
    "musl-x86_64": "Alpine x86_64",
    "musl-aarch64": "Alpine ARM64",
    "macos-arm64": "macOS Apple silicon",
    "macos-x86_64": "macOS Intel",
    "win-amd64": "Windows x86_64",
    "win-arm64": "Windows ARM64",
    "pyodide": "Pyodide (browser)",
}
STATUS_TEXT = {"wheel": "wheel", "source": "from source", "missing": "can't install", "unknown": "unknown"}
# No scripts, fetches or frames: only the stylesheet, the favicon and the inline style on the "Why?" line.
CSP = "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'"


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_key(value: str) -> tuple[int, int]:
    major, minor = value.rstrip("t").split(".", 1)
    return int(major), int(minor)


def newest_non_free_threaded(targets: list[dict]) -> str:
    pys = {t["python"] for t in targets if not str(t["python"]).endswith("t")}
    if not pys:
        sys.exit("build_pages: no non-free-threaded Python in coverage.json")
    return max(pys, key=python_key)


def join_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def describe(package: dict, columns: dict[str, int], python: str) -> str:
    """One sentence on the package's gaps for the newest Python, for the meta description."""
    name = f"{package['name']} {package['version'] or ''}".strip()
    if package.get("error"):
        return f"{name}: the latest wheelgap scan couldn't look this package up on PyPI."
    if package.get("pure"):
        return f"{name} is pure Python: it installs on Linux, Alpine, macOS, Windows, ARM and Pyodide."
    by_status: dict[str, list[str]] = {}
    for platform, index in columns.items():
        by_status.setdefault(package["results"][index], []).append(PLATFORM_NAMES[platform])
    wheel = len(by_status.get("wheel", []))
    if wheel == len(columns):
        return f"{name} ships a prebuilt wheel for all {len(columns)} platforms checked on Python {python}."
    parts = [f"{name} has a prebuilt wheel for {wheel} of {len(columns)} platforms on Python {python}"]
    if source := by_status.get("source"):
        parts.append(f"builds from source on {join_names(source)}")
    if missing := by_status.get("missing"):
        parts.append(f"can't install on {join_names(missing)}")
    if unknown := by_status.get("unknown"):
        parts.append(f"is unknown on {join_names(unknown)}")
    return "; ".join(parts) + "."


def page(package: dict, scan: dict, python: str) -> str:
    targets = scan["targets"]
    pys = list(dict.fromkeys(t["python"] for t in targets))
    platforms = [pl for pl in PLATFORM_NAMES if any(t["platform"] == pl for t in targets)]
    index = {(t["python"], t["platform"]): i for i, t in enumerate(targets)}
    # The native platforms, like the badge, so the description and the badge give the same count.
    columns = {pl: index[(python, pl)] for pl in platforms if pl != "pyodide" and (python, pl) in index}
    e = html.escape
    name, version = package["name"], package["version"] or ""
    title = f"{name} wheel coverage: Linux, Alpine, macOS, Windows, ARM, Pyodide"
    url = f"{BASE_URL}p/{canonical(name)}/"
    summary = describe(package, columns, python)

    def cell(py: str, pl: str) -> str:
        i = index.get((py, pl))
        if i is None:
            return '<td><span class="status s-none">n/a</span></td>'
        s = package["results"][i]
        return f'<td><span class="status s-{e(s)}">{e(STATUS_TEXT.get(s, s))}</span></td>'

    rows = "\n".join(
        f'          <tr><th scope="row">{e(PLATFORM_NAMES[pl])}</th>{"".join(cell(py, pl) for py in pys)}</tr>'
        for pl in platforms
    )
    sub = f"#{package['rank']} by downloads"
    if package.get("pure"):
        sub += " · pure Python: installs everywhere"
    if package.get("error"):
        sub += f" · lookup failed: {e(package['error'])}"
    sub += f' · <a href="https://pypi.org/project/{e(name)}/">PyPI</a>'
    explain = f"uvx wheelgap {name}=={version} -p {python} -t all --explain" if version else ""
    why = f'\n      <p class="sub" style="margin:12px 0 0">Why? <code>{e(explain)}</code></p>' if explain else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{CSP}">
  <title>{e(title)}</title>
  <meta name="description" content="{e(summary)}">
  <link rel="canonical" href="{e(url)}">
  <link rel="stylesheet" href="../../style.css">
  <link rel="icon" href="../../favicon.svg" type="image/svg+xml">
</head>
<body>
  <header class="wrap">
    <p class="eyebrow"><a href="../../">wheelgap tracker</a></p>
    <h1>{e(name)} wheel coverage</h1>
    <p>{e(summary)}</p>
    <p class="meta">From the wheelgap {e(str(scan["wheelgap"]))} scan of {e(str(scan["generated"])[:10])}.</p>
  </header>
  <main class="wrap">
    <div class="card">
      <h3>{e(name)} <span class="ver">{e(version)}</span></h3>
      <p class="sub">{sub}</p>
      <div class="matrix-scroll"><table class="matrix">
        <thead><tr><th>Platform</th>{"".join(f"<th>{e(py)}</th>" for py in pys)}</tr></thead>
        <tbody>
{rows}
        </tbody>
      </table></div>{why}
    </div>
    <p class="sub"><a href="../../#package={e(name)}">All {len(scan["packages"]):,} packages</a></p>
  </main>
</body>
</html>
"""


def build(coverage_path: Path, site: Path) -> int:
    scan = json.loads(coverage_path.read_text(encoding="utf-8"))
    if scan.get("schema") != SCAN_SCHEMA:
        sys.exit(f"build_pages: coverage.json schema {scan.get('schema')!r}, expected {SCAN_SCHEMA}")
    python = newest_non_free_threaded(scan["targets"])
    names: list[str] = []
    seen: set[str] = set()
    for p in scan["packages"]:
        name = canonical(p["name"])
        if not SAFE_NAME.fullmatch(name) or name in seen:
            print(f"::warning::build_pages: skipping {p['name']!r}", file=sys.stderr)
            continue
        names.append(name)
        seen.add(name)
        out = site / "p" / name
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(page(p, scan, python), encoding="utf-8")
    urls = [BASE_URL] + [f"{BASE_URL}p/{name}/" for name in names]
    sitemap = "".join(f"  <url><loc>{html.escape(u)}</loc></url>\n" for u in urls)
    (site / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{sitemap}</urlset>\n',
        encoding="utf-8",
    )
    return len(names)


if __name__ == "__main__":
    coverage, site = (Path(p) for p in sys.argv[1:3])
    print(f"pages: {build(coverage, site)} packages in {site / 'p'}")
