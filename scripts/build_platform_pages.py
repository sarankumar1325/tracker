"""Publish crawlable, JavaScript-free pages of the most-wanted missing wheels by platform.

    python3 scripts/build_platform_pages.py data/coverage.json _site/data/most-wanted.json _site campaigns.toml

Runs after the package and campaign pages so all platform URLs can be added to the same sitemap.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

if __package__:
    from . import build_campaigns, build_lab, build_pages
else:
    import build_campaigns
    import build_lab
    import build_pages

BASE = build_pages.BASE_URL
CSP = build_pages.CSP
SCAN_SCHEMA = 1
OK = ("wheel", "bundled")  # counted as covered, as on the home page


def _page(
    title: str,
    lede: str,
    meta: str,
    content: str,
    canonical: str,
    root: str,
    feed_title: str | None = None,
    feed_href: str | None = None,
) -> str:
    e = html.escape
    feed = (
        f'\n  <link rel="alternate" type="application/atom+xml" title="{e(feed_title)}" href="{e(feed_href)}">'
        if feed_title and feed_href
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="{e(CSP, quote=True)}">
  <title>{e(title)}</title>
  <meta name="description" content="{e(lede, quote=True)}">
{build_campaigns.og_tags(title, lede, canonical)}
  <link rel="canonical" href="{e(canonical, quote=True)}">{feed}
  <link rel="stylesheet" href="{root}style.css">
  <link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
</head>
<body>
  <header class="wrap">
    <p class="eyebrow"><a href="{root}">wheelgap tracker</a></p>
    <h1>{e(title)}</h1>
    <p class="lede">{e(lede)}</p>
    {meta}
  </header>
  <main class="wrap">{content}</main>
</body></html>
"""


def _table(rows: list) -> str:
    e = html.escape
    body = []
    for item in rows:
        if not isinstance(item, dict) or item.get("status") not in ("source", "missing"):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        slug = build_pages.canonical(name)
        if not build_pages.SAFE_NAME.fullmatch(slug):
            continue
        status = item["status"]
        body.append(
            f"<tr><td>{e(str(item.get('rank', '')))}</td>"
            f'<td><a href="../../p/{e(slug)}/">{e(name)}</a></td>'
            f"<td>{e(str(item.get('version', '')))}</td>"
            f'<td><span class="status s-{e(status)}">{e(build_pages.STATUS_TEXT[status])}</span></td></tr>'
        )
    if not body:
        return '<p class="note">None of the top packages is missing a wheel here.</p>'
    return (
        '<div class="matrix-scroll"><table class="matrix">'
        "<thead><tr><th>Rank</th><th>Package</th><th>Version</th><th>Status</th></tr></thead>"
        "<tbody>" + "".join(body) + "</tbody></table></div>"
    )


def build(coverage_path: Path, wanted_path: Path, site: Path, config_path: Path | None = None) -> int:
    scan = json.loads(coverage_path.read_text(encoding="utf-8"))
    wanted = json.loads(wanted_path.read_text(encoding="utf-8"))
    if scan.get("schema") != SCAN_SCHEMA:
        sys.exit(f"build_platform_pages: coverage.json schema {scan.get('schema')!r}, expected {SCAN_SCHEMA}")
    if wanted.get("generated") != scan.get("generated") or not isinstance(wanted.get("targets"), dict):
        sys.exit("build_platform_pages: most-wanted.json is not from the same scan as coverage.json")
    e = html.escape
    targets = scan["targets"]
    packages = scan["packages"]
    total = len(packages)
    meta = f'<p class="meta">From the wheelgap {e(str(scan["wheelgap"]))} scan of {e(str(scan["generated"])[:10])}.</p>'
    campaigns = build_campaigns.load_campaigns(config_path) if config_path is not None and config_path.exists() else []
    newest = build_pages.newest_non_free_threaded(targets)
    # Declared lab coverage. A label's platform part, not TARGETS[...]["platform"] (that's the interpreter's platform).
    lab_platforms = {label.split(" ", 1)[1] for label in build_lab.TARGETS}
    out = site / "platforms"
    out.mkdir(parents=True, exist_ok=True)
    urls = [f"{BASE}platforms/"]
    index_links = []

    for platform, friendly in build_pages.PLATFORM_NAMES.items():
        # The newest non-free-threaded Python this platform has a target for (Pyodide lags behind).
        platform_targets = [t for t in targets if t["platform"] == platform and not str(t["python"]).endswith("t")]
        if not platform_targets:
            continue
        python = build_pages.newest_non_free_threaded(platform_targets)
        index = next(i for i, t in enumerate(targets) if t["python"] == python and t["platform"] == platform)
        label = targets[index]["label"]
        ok = sum(p["results"][index] in OK for p in packages)
        percent = f"{ok * 100 / total:.1f}" if total else "0.0"
        what = "a prebuilt wheel or a Pyodide build" if platform == "pyodide" else "a prebuilt wheel"
        lede = f"{ok:,} of the top {total:,} PyPI packages ({percent}%) have {what} on {friendly} for Python {python}."
        source = wanted["targets"].get(label, [])
        table = _table(source[:50] if isinstance(source, list) else [])

        campaign_links = []
        for c in campaigns:
            if c["platform"] != platform:
                continue
            c_python = c.get("python") or newest
            text = c["title"] if c_python == python else f"{c['title']} (Python {c_python})"
            campaign_links.append(f'<a href="../../campaigns/{e(c["id"])}/">{e(text)}</a>')
        extras = ("<p>Campaign: " + " · ".join(campaign_links) + "</p>") if campaign_links else ""
        if platform in lab_platforms:
            extras += '<p><a href="../../#lab-section">See build lab results</a> for this platform.</p>'

        title = f"Python {python} packages without {friendly} wheels"
        content = (
            f"<section><h2>Most-wanted wheels for Python {e(python)}</h2>{table}{extras}"
            '<p><a href="../../">Search every package</a></p></section>'
        )
        url = f"{BASE}platforms/{platform}/"
        folder = out / platform
        folder.mkdir(exist_ok=True)
        (folder / "index.html").write_text(
            _page(
                title,
                lede,
                meta,
                content,
                url,
                "../../",
                feed_title=f"New {platform} wheels",
                feed_href=f"../../new/{platform}.xml",
            ),
            encoding="utf-8",
        )
        index_links.append(f'<li><a href="{e(platform)}/">{e(friendly)}</a></li>')
        urls.append(url)

    main = _page(
        "Wheel coverage by platform",
        "The most-downloaded PyPI packages without a wheel, one page per platform.",
        meta,
        "<section><h2>Platforms</h2><ul>" + "".join(index_links) + "</ul></section>",
        f"{BASE}platforms/",
        "../",
    )
    (out / "index.html").write_text(main, encoding="utf-8")
    build_campaigns.add_to_sitemap(site, urls)
    return len(urls) - 1


if __name__ == "__main__":
    coverage, wanted, site = (Path(p) for p in sys.argv[1:4])
    config = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    print(f"platforms: {build(coverage, wanted, site, config)} pages in {site / 'platforms'}")
