"""Publish new wheels (#152): a page and per-platform Atom feeds from data/changes.json.

    python scripts/build_new_wheels.py data/changes.json data/coverage.json _site

Writes <site>/new/index.html (the latest wheel gains, newest first), <site>/new.xml (an Atom feed,
one entry per release that gained wheels), and <site>/new/<platform>.xml for each platform in
build_pages.PLATFORM_NAMES (with only that platform's targets). Adds the page to <site>/sitemap.xml.
A package links to its page on this site while it's in the current scan (coverage.json), and to
PyPI once it has left the top N.
Plain HTML, no JavaScript, under the site's usual CSP.
"""

from __future__ import annotations

import datetime
import html
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

if __package__:  # imported as scripts.build_new_wheels (the tests)
    from . import build_campaigns, build_drops, build_pages
    package_url = build_drops.package_url
else:
    import build_campaigns
    import build_drops
    import build_pages
    package_url = build_drops.package_url

BASE_URL = build_campaigns.BASE_URL
CSP = build_campaigns.CSP
PAGE_LIMIT = 200  # releases on the page
FEED_LIMIT = 50

WAS_TEXT = {
    "source": "built from source",
    "missing": "couldn't install",
}


def filter_undo_gains(changes: list[dict]) -> list[dict]:
    """Leave out any gain that only undoes a loss of the same package, version, and target
    in the previous 7 days of changes.json (a release whose wheels were still uploading)."""
    sorted_days = sorted(
        [d for d in changes if isinstance(d, dict) and "date" in d],
        key=lambda d: d["date"],
    )
    losses: list[tuple[str, str, str, datetime.date]] = []
    for day in sorted_days:
        try:
            d_date = datetime.date.fromisoformat(day["date"])
        except ValueError:
            continue
        for l in day.get("lost", []):
            if isinstance(l, dict) and "name" in l and "version" in l and "target" in l:
                losses.append((build_campaigns.canonical(l["name"]), str(l["version"]), str(l["target"]), d_date))

    kept: list[dict] = []
    for day in sorted_days:
        try:
            g_date = datetime.date.fromisoformat(day["date"])
        except ValueError:
            continue
        for g in day.get("gained", []):
            if not (isinstance(g, dict) and "name" in g and "version" in g and "target" in g):
                continue
            canon = build_campaigns.canonical(g["name"])
            ver = str(g["version"])
            tgt = str(g["target"])
            matched_idx = -1
            for i, (lname, lver, ltgt, ldate) in enumerate(losses):
                if lname == canon and lver == ver and ltgt == tgt and 0 <= (g_date - ldate).days <= 7:
                    matched_idx = i
            if matched_idx >= 0:
                losses.pop(matched_idx)
                continue
            kept.append({
                "date": day["date"],
                "name": g["name"],
                "version": str(g["version"]),
                "target": str(g["target"]),
                "from": g.get("from", ""),
                "to": g.get("to", "wheel"),
            })
    return kept


def releases(gains: list[dict]) -> list[dict]:
    """One item per (date, package, version), targets in file order, newest first."""
    grouped: dict[tuple[str, str, str], dict] = {}
    for g in gains:
        key = (g["date"], g["name"], g["version"])
        if key not in grouped:
            grouped[key] = {
                "date": g["date"],
                "name": g["name"],
                "version": g["version"],
                "targets": [],
                "froms": [],
                "details": [],
            }
        item = grouped[key]
        if g["target"] not in item["targets"]:
            item["targets"].append(g["target"])
            item["froms"].append(g.get("from", ""))
            item["details"].append({"target": g["target"], "from": g.get("from", "")})

    result = []
    for item in grouped.values():
        froms = item.pop("froms")
        was_labels = [WAS_TEXT.get(f, f) for f in froms if f]
        unique_was = list(dict.fromkeys(was_labels))
        item["was"] = ", ".join(unique_was) if unique_was else ""
        item["from"] = froms[0] if froms else ""
        result.append(item)

    result.sort(key=lambda r: r["date"], reverse=True)
    return result


def for_platform(items: list[dict], platform: str) -> list[dict]:
    """Filter releases to only those with targets on `platform`, with only that platform's targets."""
    plat_items = []
    for r in items:
        matching = [
            d for d in r.get("details", [])
            if (d["target"].split(" ", 1)[1] if " " in d["target"] else d["target"]) == platform
        ]
        if not matching:
            continue
        targets = [d["target"] for d in matching]
        froms = [d.get("from", "") for d in matching]
        was_labels = [WAS_TEXT.get(f, f) for f in froms if f]
        unique_was = list(dict.fromkeys(was_labels))
        plat_items.append({
            "date": r["date"],
            "name": r["name"],
            "version": r["version"],
            "targets": targets,
            "was": ", ".join(unique_was) if unique_was else "",
            "from": froms[0] if froms else "",
            "details": matching,
        })
    return plat_items


def page(items: list[dict], scanned: set[str]) -> str:
    e = html.escape
    rows = "\n".join(
        f'          <tr><td>{e(r["date"])}</td><td><a href="{e(package_url(r["name"], scanned, "../"))}">{e(r["name"])}</a></td>'
        f'<td><strong>{e(r["version"])}</strong></td>'
        f'<td>{e(", ".join(r["targets"]))}</td>'
        f'<td>{e(r["was"])}</td></tr>'
        for r in items[:PAGE_LIMIT]
    )
    body = (
        '        <div class="matrix-scroll"><table class="matrix">\n'
        "          <thead><tr><th>Date</th><th>Package</th><th>Version</th><th>Gained</th><th>Was</th></tr></thead>\n"
        f"          <tbody>\n{rows}\n          </tbody>\n"
        "        </table></div>\n"
        if items
        else '        <p class="note">No new wheels recorded yet.</p>\n'
    )
    more = f" The page shows the latest {PAGE_LIMIT}." if len(items) > PAGE_LIMIT else ""
    summary = "Top PyPI packages that recently gained prebuilt wheels."
    platform_links = " · ".join(
        f'<a href="{e(plat)}.xml">{e(plat)}</a>'
        for plat in build_pages.PLATFORM_NAMES
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{CSP}">
  <title>New wheels · wheelgap tracker</title>
  <meta name="description" content="{e(summary)}">
{build_campaigns.og_tags("New wheels · wheelgap tracker", summary, BASE_URL + "new/")}
  <link rel="canonical" href="{e(BASE_URL)}new/">
  <link rel="alternate" type="application/atom+xml" title="New wheels" href="../new.xml">
  <link rel="stylesheet" href="../style.css">
  <link rel="icon" href="../favicon.svg" type="image/svg+xml">
</head>
<body>
  <header class="wrap">
    <p class="eyebrow"><a href="../">wheelgap tracker</a></p>
    <h1>New wheels</h1>
    <p class="lede">Top packages that recently shipped a prebuilt wheel for a platform where they previously built from source or couldn't install.</p>
  </header>
  <main class="wrap">
    <section>
      <h2>Latest new wheels</h2>
      <p class="note">From the nightly comparison of wheelgap coverage scans. Only changes to prebuilt wheels are listed; releases whose wheels were still uploading (gaining wheels within 7 days of losing them) are excluded.{more} Subscribe: <a href="../new.xml">Atom feed</a>. Feeds by platform: {platform_links}.</p>
{body}    </section>
  </main>
</body>
</html>
"""


def feed(items: list[dict], updated: str, scanned: set[str], platform: str | None = None) -> str:
    x = xml_escape
    entries = []
    for r in items[:FEED_LIMIT]:
        targets = ", ".join(r["targets"])
        # The night is part of the id: a release can gain more targets on a later night, and each is news.
        ident = f"{BASE_URL}new/#{r['date']}-{build_campaigns.canonical(r['name'])}-{r['version']}"
        if platform:
            ident = f"{ident}-{platform}"
        summary_was = f" (was {x(r['was'])})" if r.get("was") else ""
        entries.append(
            "  <entry>\n"
            f"    <title>{x(r['name'])} {x(r['version'])} gained {x(targets)}</title>\n"
            f'    <link href="{html.escape(package_url(r["name"], scanned, BASE_URL))}"/>\n'
            f"    <id>{x(ident)}</id>\n"
            f"    <updated>{x(r['date'])}T00:00:00Z</updated>\n"
            f"    <summary>{x(r['name'])} {x(r['version'])} gained {x(targets)} wheels{summary_was}.</summary>\n"
            "  </entry>\n"
        )
    if platform:
        title = f"wheelgap tracker: new {platform} wheels"
        self_href = f"{BASE_URL}new/{platform}.xml"
        page_href = f"{BASE_URL}platforms/{platform}/"
    else:
        title = "wheelgap tracker: new wheels"
        self_href = f"{BASE_URL}new.xml"
        page_href = f"{BASE_URL}new/"

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <title>{x(title)}</title>\n"
        f'  <link href="{x(page_href)}"/>\n'
        f'  <link rel="self" href="{x(self_href)}"/>\n'
        f"  <id>{x(self_href)}</id>\n"
        f"  <updated>{x(updated)}T00:00:00Z</updated>\n"
        "  <author><name>wheelgap tracker</name></author>\n"
        f"{''.join(entries)}"
        "</feed>\n"
    )


def build(changes_path: Path, coverage_path: Path, site: Path) -> int:
    changes = json.loads(changes_path.read_text(encoding="utf-8")) if changes_path.exists() else []
    scan = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else {}
    scanned = {build_campaigns.canonical(p["name"]) for p in scan.get("packages", [])}

    gains = filter_undo_gains(changes)
    items = releases(gains)

    (site / "new").mkdir(parents=True, exist_ok=True)
    (site / "new" / "index.html").write_text(page(items, scanned), encoding="utf-8")

    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    updated = items[0]["date"] if items else today
    (site / "new.xml").write_text(feed(items, updated, scanned), encoding="utf-8")

    for platform in build_pages.PLATFORM_NAMES:
        plat_items = for_platform(items, platform)
        plat_updated = plat_items[0]["date"] if plat_items else updated
        (site / "new" / f"{platform}.xml").write_text(
            feed(plat_items, plat_updated, scanned, platform=platform), encoding="utf-8"
        )

    build_campaigns.add_to_sitemap(site, [f"{BASE_URL}new/"])
    return len(items)


if __name__ == "__main__":
    changes, coverage, site = (Path(p) for p in sys.argv[1:4])
    print(f"new: {build(changes, coverage, site)} releases on the page")
