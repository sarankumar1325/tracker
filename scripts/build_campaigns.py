"""Build static campaign pages from a wheelgap coverage scan.

    python scripts/build_campaigns.py data/coverage.json data/history.json \
        data/changes.json campaigns.toml _site

Writes <site>/campaigns/<id>/index.html for each campaign in the TOML file, and
adds those URLs to <site>/sitemap.xml (created by build_pages.py, or written
here if it is missing). Runs at publish time; the pages are not committed.
The pages are plain HTML (no JavaScript) and reuse site/style.css.
"""

from __future__ import annotations

import html
import json
import re
import sys
import tomllib
from pathlib import Path

SCAN_SCHEMA = 1
SAFE_ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
SAFE_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
BASE_URL = "https://wheelgap.github.io/tracker/"
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
CSP = "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'"
ASK_FIRST = (
    "Ask upstream first: open one issue on the project's tracker, with a link to this "
    "campaign and the platforms that are missing, and wait for a maintainer to agree "
    "before sending a pull request."
)


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_key(value: str) -> tuple[int, int]:
    major, minor = value.rstrip("t").split(".", 1)
    return int(major), int(minor)


def newest_non_free_threaded(targets: list[dict]) -> str:
    pys = {t["python"] for t in targets if not str(t["python"]).endswith("t")}
    if not pys:
        sys.exit("build_campaigns: no non-free-threaded Python in coverage.json")
    return max(pys, key=python_key)


def load_campaigns(config_path: Path) -> list[dict]:
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    campaigns = data.get("campaign", [])
    if not campaigns:
        sys.exit(f"build_campaigns: no [[campaign]] entries in {config_path}")
    seen: set[str] = set()
    for campaign in campaigns:
        for field in ("id", "title", "platform", "top", "start"):
            if field not in campaign:
                sys.exit(f"build_campaigns: campaign is missing {field!r}")
        ident = campaign["id"]
        if not SAFE_ID.fullmatch(ident):
            sys.exit(f"build_campaigns: invalid campaign id {ident!r}")
        if ident in seen:
            sys.exit(f"build_campaigns: duplicate campaign id {ident!r}")
        seen.add(ident)
        if not isinstance(campaign["top"], int) or campaign["top"] < 1:
            sys.exit(f"build_campaigns: campaign {ident!r} has a bad top count")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(campaign["start"])):
            sys.exit(f"build_campaigns: campaign {ident!r} start must be YYYY-MM-DD")
    return campaigns


def target_index(targets: list[dict], python: str, platform: str) -> int:
    for i, target in enumerate(targets):
        if target["python"] == python and target["platform"] == platform:
            return i
    sys.exit(f"build_campaigns: no {python} {platform} target in coverage.json")


def target_label(targets: list[dict], python: str, platform: str) -> str:
    return targets[target_index(targets, python, platform)]["label"]


def top_packages(scan: dict, top: int) -> list[dict]:
    return sorted((p for p in scan["packages"] if p["rank"] <= top), key=lambda p: p["rank"])


def package_status(package: dict, index: int) -> str:
    if package.get("error"):
        return "error"
    return package["results"][index]


def has_wheel(package: dict, index: int) -> bool:
    return package_status(package, index) == "wheel"


def coverage_counts(packages: list[dict], index: int) -> tuple[int, int]:
    wheels = sum(1 for p in packages if has_wheel(p, index))
    return wheels, len(packages)


def trend(history: list[dict], label: str) -> list[dict]:
    """Per-day wheel counts for a target label, across the whole nightly scan.

    history.json only stores those full-scan totals, not a top-N slice, so the
    trend is labelled as the nightly scan rather than the campaign's top N.
    """
    rows = []
    for entry in history:
        cell = entry.get("summary", {}).get(label)
        if not cell:
            continue
        packages = entry.get("packages") or 0
        wheels = cell.get("wheel", 0)
        rows.append({
            "date": entry["date"],
            "wheels": wheels,
            "packages": packages,
            "percent": (100.0 * wheels / packages) if packages else 0.0,
        })
    return rows


def todo_list(packages: list[dict], index: int) -> list[dict]:
    rows = []
    for package in packages:
        if has_wheel(package, index):
            continue
        status = package_status(package, index)
        rows.append({
            "rank": package["rank"],
            "name": package["name"],
            "version": package["version"] or "",
            "status": status,
            "canonical": canonical(package["name"]),
        })
    return rows


def done_list(changes: list[dict], *, label: str, start: str, top_names: set[str]) -> list[dict]:
    """Packages in the current top N that gained a wheel on this target on or after start."""
    seen: set[str] = set()
    rows = []
    for entry in changes:
        if entry.get("date", "") < start:
            continue
        for item in entry.get("gained", []):
            if item.get("target") != label or item.get("to") != "wheel":
                continue
            name = item["name"]
            if name not in top_names or name in seen:
                continue
            seen.add(name)
            rows.append({
                "date": entry["date"],
                "name": name,
                "version": item.get("version") or "",
                "canonical": canonical(name),
                "frm": item.get("from") or "",
            })
    rows.sort(key=lambda r: (r["date"], r["name"]))
    return rows


def source_url(package: dict) -> str | None:
    """Return a homepage or repo URL when coverage.json carries project_urls."""
    urls = package.get("project_urls") or {}
    if not isinstance(urls, dict):
        return None
    for key in ("Source", "source", "Repository", "repository", "Homepage", "homepage", "Home", "home"):
        value = urls.get(key)
        if isinstance(value, str) and value.startswith("https://"):
            return value
    return None


def percent(wheels: int, total: int) -> str:
    if not total:
        return "0%"
    value = 100.0 * wheels / total
    if value == int(value):
        return f"{int(value)}%"
    return f"{value:.1f}%"



def article(name: str) -> str:
    return "an" if name[:1].lower() in "aeiou" else "a"


def rows_html(items: list[dict], *, kind: str, include_source: bool) -> str:
    e = html.escape
    if not items:
        empty = "None yet." if kind == "done" else "Every package in the set already has a wheel."
        return f'        <p class="note">{empty}</p>\n'
    head = "<th>Rank</th><th>Package</th><th>Status</th>"
    if kind == "done":
        head = "<th>Date</th><th>Package</th><th>Was</th>"
    if include_source:
        head += "<th>Source</th>"
    body = []
    for item in items:
        name = item["name"]
        slug = item["canonical"]
        pkg = (
            f'<a href="../../p/{e(slug)}/">{e(name)}</a>'
            f' <span class="ver">{e(item["version"])}</span>'
            f' · <a href="https://pypi.org/project/{e(name)}/">PyPI</a>'
        )
        if kind == "done":
            cells = f'<td>{e(item["date"])}</td><td>{pkg}</td><td>{e(item["frm"])}</td>'
        else:
            status = item["status"]
            label = "lookup failed" if status == "error" else STATUS_TEXT.get(status, status)
            cells = (
                f'<td>{item["rank"]}</td><td>{pkg}</td>'
                f'<td><span class="status s-{e(status)}">{e(label)}</span></td>'
            )
        if include_source:
            url = item.get("source")
            cells += f'<td><a href="{e(url)}">{e(url)}</a></td>' if url else "<td></td>"
        body.append(f"          <tr>{cells}</tr>")
    return (
        '        <div class="matrix-scroll"><table class="matrix">\n'
        f"          <thead><tr>{head}</tr></thead>\n"
        "          <tbody>\n"
        + "\n".join(body)
        + "\n          </tbody>\n"
        "        </table></div>\n"
    )


def trend_html(rows: list[dict], label: str) -> str:
    e = html.escape
    if not rows:
        return '        <p class="note">No history has been recorded for this target yet.</p>\n'
    body = "\n".join(
        f'          <tr><td>{e(r["date"])}</td>'
        f'<td>{r["wheels"]:,} / {r["packages"]:,}</td>'
        f'<td>{e(percent(r["wheels"], r["packages"]))}</td></tr>'
        for r in rows
    )
    return (
        f'        <p class="note">Nightly scan totals for {e(label)} (every package in the '
        "scan, not only this campaign's top N; history.json does not keep a top-N slice).</p>\n"
        '        <div class="matrix-scroll"><table class="matrix">\n'
        "          <thead><tr><th>Date</th><th>Wheels</th><th>Share</th></tr></thead>\n"
        f"          <tbody>\n{body}\n          </tbody>\n"
        "        </table></div>\n"
    )


def page(campaign: dict, scan: dict, history: list, changes: list, python: str) -> str:
    e = html.escape
    platform = campaign["platform"]
    top = campaign["top"]
    index = target_index(scan["targets"], python, platform)
    label = scan["targets"][index]["label"]
    packages = top_packages(scan, top)
    wheels, total = coverage_counts(packages, index)
    share = percent(wheels, total)
    todo = todo_list(packages, index)
    include_source = any(source_url(p) for p in scan["packages"])
    if include_source:
        for item in todo:
            item["source"] = source_url(next(p for p in packages if p["name"] == item["name"]))
    done = done_list(changes, label=label, start=campaign["start"], top_names={p["name"] for p in packages})
    platform_name = PLATFORM_NAMES.get(platform, platform)
    title = campaign["title"]
    url = f"{BASE_URL}campaigns/{campaign['id']}/"
    summary = (
        f"{wheels} of the top {total} packages ship {article(platform_name)} {platform_name} wheel on Python {python} "
        f"({share}). {len(todo)} still need one."
    )
    how_to = campaign.get("how_to")
    how_to_html = f' <a href="{e(how_to)}">How to ask for a missing wheel</a>.' if how_to else ""
    generated = str(scan["generated"])[:10]
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
    <h1>{e(title)}</h1>
    <p class="lede">{e(platform_name)} ({e(platform)}) is one of the thinnest native platforms on the tracker, and it is what you get with <code>python:*-alpine</code> images on Graviton and Apple-silicon CI. This page turns that gap into a list people can work through.</p>
    <p class="meta">From the wheelgap {e(str(scan["wheelgap"]))} scan of {e(generated)}, using Python {e(python)} (the newest non-free-threaded Python, as the badges do).</p>
  </header>
  <main class="wrap">
    <section>
      <h2>Coverage</h2>
      <p><strong>{e(share)}</strong> of the top {total} packages have {e(article(platform_name))} {e(platform_name)} wheel today ({wheels:,} of {total:,}).</p>
{trend_html(trend(history, label), label)}    </section>
    <section>
      <h2>To do</h2>
      <p class="note">{len(todo)} of the top {top} packages still have no {e(platform_name)} wheel, most-downloaded first.{how_to_html} {e(ASK_FIRST)}</p>
{rows_html(todo, kind="todo", include_source=include_source)}    </section>
    <section>
      <h2>Done</h2>
      <p class="note">Packages in the current top {top} that gained {e(article(platform_name))} {e(platform_name)} wheel on or after {e(campaign["start"])}, from the nightly change log.</p>
{rows_html(done, kind="done", include_source=False)}    </section>
  </main>
</body>
</html>
"""


def add_to_sitemap(site: Path, urls: list[str]) -> None:
    path = site / "sitemap.xml"
    existing: list[str] = []
    if path.exists():
        existing = re.findall(r"<loc>([^<]*)</loc>", path.read_text(encoding="utf-8"))
    seen = set(existing)
    if BASE_URL not in seen:
        existing.insert(0, BASE_URL)
        seen.add(BASE_URL)
    for url in urls:
        if url not in seen:
            existing.append(url)
            seen.add(url)
    body = "".join(f"  <url><loc>{html.escape(u)}</loc></url>\n" for u in existing)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n',
        encoding="utf-8",
    )


def build(coverage_path: Path, history_path: Path, changes_path: Path, config_path: Path, site: Path) -> int:
    scan = json.loads(coverage_path.read_text(encoding="utf-8"))
    if scan.get("schema") != SCAN_SCHEMA:
        sys.exit(f"build_campaigns: coverage.json schema {scan.get('schema')!r}, expected {SCAN_SCHEMA}")
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
    changes = json.loads(changes_path.read_text(encoding="utf-8")) if changes_path.exists() else []
    campaigns = load_campaigns(config_path)
    python = newest_non_free_threaded(scan["targets"])
    urls: list[str] = []
    for campaign in campaigns:
        ident = campaign["id"]
        out = site / "campaigns" / ident
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(page(campaign, scan, history, changes, python), encoding="utf-8")
        urls.append(f"{BASE_URL}campaigns/{ident}/")
    add_to_sitemap(site, urls)
    return len(campaigns)


if __name__ == "__main__":
    coverage, history, changes, config, site = (Path(p) for p in sys.argv[1:6])
    print(f"campaigns: {build(coverage, history, changes, config, site)} pages in {site / 'campaigns'}")
