"""Publish the dropped platforms (#75): a page and an Atom feed from data/drops.json.

    python scripts/build_drops.py data/drops.json data/coverage.json _site

Writes <site>/drops/index.html (the latest drops, newest first) and <site>/drops.xml (an Atom feed,
one entry per release that dropped a platform), and adds the page to <site>/sitemap.xml. A package
links to its page on this site while it's in the current scan (coverage.json), and to PyPI once it
has left the top N. The JSON itself is published as data/drops.json with the rest of data/. Runs at
publish time; nothing is committed. Plain HTML, no JavaScript, under the site's usual CSP.
"""

from __future__ import annotations

import datetime
import html
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

if __package__:  # imported as scripts.build_drops (the tests)
    from . import build_campaigns
else:
    import build_campaigns

BASE_URL = build_campaigns.BASE_URL
CSP = build_campaigns.CSP
PAGE_LIMIT = 200  # releases on the page; drops.json has the full year
FEED_LIMIT = 50


def releases(drops: list[dict]) -> list[dict]:
    """One item per (date, package, version), targets in file order, newest first as drops.json is."""
    grouped: dict[tuple[str, str, str], dict] = {}
    for d in drops:
        key = (d["date"], d["name"], d["version"])
        item = grouped.setdefault(key, {"date": d["date"], "name": d["name"], "from": d["from"],
                                        "version": d["version"], "targets": []})
        item["targets"].append(d["target"])
    return list(grouped.values())


def package_url(name: str, scanned: set[str], prefix: str) -> str:
    """The package's page under `prefix` (the site root, relative or absolute) while it's in the current
    scan, so the page exists; its PyPI page once it has left the top N."""
    key = build_campaigns.canonical(name)
    return f"{prefix}p/{key}/" if key in scanned else f"https://pypi.org/project/{key}/"


def page(items: list[dict], waiting: int, scanned: set[str]) -> str:
    e = html.escape
    rows = "\n".join(
        f'          <tr><td>{e(r["date"])}</td><td><a href="{e(package_url(r["name"], scanned, "../"))}">{e(r["name"])}</a></td>'
        f'<td>{e(r["from"])} → <strong>{e(r["version"])}</strong></td>'
        f'<td>{e(", ".join(r["targets"]))}</td></tr>'
        for r in items[:PAGE_LIMIT]
    )
    body = (
        '        <div class="matrix-scroll"><table class="matrix">\n'
        "          <thead><tr><th>Date</th><th>Package</th><th>Release</th><th>Dropped</th></tr></thead>\n"
        f"          <tbody>\n{rows}\n          </tbody>\n"
        "        </table></div>\n"
        if items
        else '        <p class="note">No drops recorded yet.</p>\n'
    )
    more = f" The page shows the latest {PAGE_LIMIT}." if len(items) > PAGE_LIMIT else ""
    pending = (
        f" {waiting} new release{'' if waiting == 1 else 's'} missing wheels (maybe still uploading) "
        f"{'is' if waiting == 1 else 'are'} waiting for a later scan."
        if waiting
        else ""
    )
    summary = "Top PyPI packages whose latest release dropped a platform's wheel the previous release had."
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{CSP}">
  <title>Dropped platforms · wheelgap tracker</title>
  <meta name="description" content="{e(summary)}">
  <link rel="canonical" href="{e(BASE_URL)}drops/">
  <link rel="alternate" type="application/atom+xml" title="Dropped platforms" href="../drops.xml">
  <link rel="stylesheet" href="../style.css">
  <link rel="icon" href="../favicon.svg" type="image/svg+xml">
</head>
<body>
  <header class="wrap">
    <p class="eyebrow"><a href="../">wheelgap tracker</a></p>
    <h1>Dropped platforms</h1>
    <p class="lede">The day a top package's new release has no wheel for a platform its previous release had one for. Projects that depend on it find out at install time, one failed build at a time; this page and its feed tell you the day it happens.</p>
  </header>
  <main class="wrap">
    <section>
      <h2>Latest drops</h2>
      <p class="note">Compared with the release the previous nightly scan saw. A missing wheel is listed only if the next night's scan still finds the same release without it, since wheels are often still uploading the night a release comes out; a release with no wheel at all yet waits until one shows up (up to a week), and a release that is yanked is taken off the list. When a release has no wheel left for one Python version (it ended support for that Python), that Python's platforms aren't listed.{pending}{more} Subscribe: <a href="../drops.xml">Atom feed</a>. As JSON: <a href="../data/drops.json">data/drops.json</a>.</p>
{body}    </section>
  </main>
</body>
</html>
"""


def feed(items: list[dict], updated: str, scanned: set[str]) -> str:
    x = xml_escape
    entries = []
    for r in items[:FEED_LIMIT]:
        targets = ", ".join(r["targets"])
        ident = f"{BASE_URL}drops/#{build_campaigns.canonical(r['name'])}-{r['version']}"
        entries.append(
            "  <entry>\n"
            f"    <title>{x(r['name'])} {x(r['version'])} dropped {x(targets)}</title>\n"
            f'    <link href="{html.escape(package_url(r["name"], scanned, BASE_URL))}"/>\n'
            f"    <id>{x(ident)}</id>\n"
            f"    <updated>{x(r['date'])}T00:00:00Z</updated>\n"
            f"    <summary>{x(r['name'])} {x(r['from'])} had a wheel for {x(targets)}; {x(r['version'])} has none.</summary>\n"
            "  </entry>\n"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "  <title>wheelgap tracker: dropped platforms</title>\n"
        f'  <link href="{x(BASE_URL)}drops/"/>\n'
        f'  <link rel="self" href="{x(BASE_URL)}drops.xml"/>\n'
        f"  <id>{x(BASE_URL)}drops.xml</id>\n"
        f"  <updated>{x(updated)}T00:00:00Z</updated>\n"
        "  <author><name>wheelgap tracker</name></author>\n"
        f"{''.join(entries)}"
        "</feed>\n"
    )


def build(drops_path: Path, coverage_path: Path, site: Path) -> int:
    data = json.loads(drops_path.read_text(encoding="utf-8")) if drops_path.exists() else {"drops": [], "waiting": []}
    scan = json.loads(coverage_path.read_text(encoding="utf-8"))
    scanned = {build_campaigns.canonical(p["name"]) for p in scan["packages"]}
    items = releases(data.get("drops", []))
    (site / "drops").mkdir(parents=True, exist_ok=True)
    (site / "drops" / "index.html").write_text(page(items, len(data.get("waiting", [])), scanned), encoding="utf-8")
    updated = items[0]["date"] if items else datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    (site / "drops.xml").write_text(feed(items, updated, scanned), encoding="utf-8")
    build_campaigns.add_to_sitemap(site, [f"{BASE_URL}drops/"])
    return len(items)


if __name__ == "__main__":
    drops, coverage, site = (Path(p) for p in sys.argv[1:4])
    print(f"drops: {build(drops, coverage, site)} releases on the page")
