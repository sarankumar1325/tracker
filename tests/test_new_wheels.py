"""New wheels (#152): grouping, per-platform feeds, 7-day undo rule, and escaping."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts import build_new_wheels, build_pages


def write_coverage(tmp_path, names):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"packages": [{"name": n} for n in names]}), encoding="utf-8")
    return path


def test_releases_grouped_per_release_and_newest_first():
    gains = [
        {"date": "2026-11-16", "name": "pkg-a", "version": "1.0", "target": "3.15 linux-x86_64", "from": "source"},
        {"date": "2026-11-16", "name": "pkg-a", "version": "1.0", "target": "3.15 win-amd64", "from": "source"},
        {"date": "2026-11-17", "name": "pkg-b", "version": "2.0", "target": "3.15 macos-arm64", "from": "missing"},
    ]
    items = build_new_wheels.releases(gains)
    assert len(items) == 2
    # Newest first
    assert items[0]["date"] == "2026-11-17"
    assert items[0]["name"] == "pkg-b"
    assert items[0]["targets"] == ["3.15 macos-arm64"]
    assert items[0]["was"] == "couldn't install"

    assert items[1]["date"] == "2026-11-16"
    assert items[1]["name"] == "pkg-a"
    assert items[1]["targets"] == ["3.15 linux-x86_64", "3.15 win-amd64"]
    assert items[1]["was"] == "built from source"


def test_seven_day_undo_rule():
    # A loss on 2026-11-10 of pkg 1.0 on win-arm64
    # A gain on 2026-11-12 of pkg 1.0 on win-arm64 (2 days later -> undo, filtered out)
    # A gain on 2026-11-12 of pkg 1.0 on linux-x86_64 (no loss -> kept)
    # A loss on 2026-11-01 of other 2.0 on win-amd64
    # A gain on 2026-11-10 of other 2.0 on win-amd64 (9 days later -> kept)
    changes = [
        {
            "date": "2026-11-01",
            "lost": [{"name": "other", "version": "2.0", "target": "3.15 win-amd64", "from": "wheel", "to": "missing"}],
            "gained": [],
        },
        {
            "date": "2026-11-10",
            "lost": [{"name": "pkg", "version": "1.0", "target": "3.15 win-arm64", "from": "wheel", "to": "missing"}],
            "gained": [
                {"name": "other", "version": "2.0", "target": "3.15 win-amd64", "from": "missing", "to": "wheel"},
            ],
        },
        {
            "date": "2026-11-12",
            "lost": [],
            "gained": [
                {"name": "pkg", "version": "1.0", "target": "3.15 win-arm64", "from": "missing", "to": "wheel"},
                {"name": "pkg", "version": "1.0", "target": "3.15 linux-x86_64", "from": "source", "to": "wheel"},
            ],
        },
    ]
    kept = build_new_wheels.filter_undo_gains(changes)
    targets = [(g["name"], g["target"]) for g in kept]
    assert ("pkg", "3.15 win-arm64") not in targets
    assert ("pkg", "3.15 linux-x86_64") in targets
    assert ("other", "3.15 win-amd64") in targets


def test_per_platform_feed_has_only_its_platform():
    items = [
        {
            "date": "2026-11-17",
            "name": "multi-pkg",
            "version": "1.0",
            "targets": ["3.15 win-arm64", "3.15 linux-x86_64"],
            "details": [
                {"target": "3.15 win-arm64", "from": "source"},
                {"target": "3.15 linux-x86_64", "from": "missing"},
            ],
            "was": "built from source, couldn't install",
        },
        {
            "date": "2026-11-17",
            "name": "linux-only",
            "version": "2.0",
            "targets": ["3.15 linux-x86_64"],
            "details": [
                {"target": "3.15 linux-x86_64", "from": "source"},
            ],
            "was": "built from source",
        },
    ]
    win_arm64_items = build_new_wheels.for_platform(items, "win-arm64")
    assert len(win_arm64_items) == 1
    assert win_arm64_items[0]["name"] == "multi-pkg"
    assert win_arm64_items[0]["targets"] == ["3.15 win-arm64"]
    assert win_arm64_items[0]["was"] == "built from source"

    linux_items = build_new_wheels.for_platform(items, "linux-x86_64")
    assert len(linux_items) == 2
    assert [r["name"] for r in linux_items] == ["multi-pkg", "linux-only"]
    assert linux_items[0]["targets"] == ["3.15 linux-x86_64"]
    assert linux_items[0]["was"] == "couldn't install"

    macos_items = build_new_wheels.for_platform(items, "macos-arm64")
    assert len(macos_items) == 0


def test_page_and_feeds_and_escaping(tmp_path):
    changes = [
        {
            "date": "2026-11-17",
            "gained": [
                {"name": "Evil<b>&Co", "version": "2.0", "target": "3.15 win-arm64", "from": "source", "to": "wheel"},
                {"name": "Evil<b>&Co", "version": "2.0", "target": "3.15 win-amd64", "from": "source", "to": "wheel"},
                {"name": "cryptography", "version": "46.0.4", "target": "3.15 win-arm64", "from": "missing", "to": "wheel"},
            ],
            "lost": [],
        },
        {
            "date": "2026-11-16",
            "gained": [
                {"name": "Old_Pkg", "version": "4.0", "target": "3.15 linux-x86_64", "from": "source", "to": "wheel"},
            ],
            "lost": [],
        },
    ]
    changes_path = tmp_path / "changes.json"
    changes_path.write_text(json.dumps(changes), encoding="utf-8")
    coverage = write_coverage(tmp_path, ["Evil<b>&Co", "cryptography"])  # Old_Pkg has left the top N
    site = tmp_path / "site"

    count = build_new_wheels.build(changes_path, coverage, site)
    assert count == 3  # Evil<b>&Co, cryptography, Old_Pkg

    # Check HTML page
    page = (site / "new" / "index.html").read_text(encoding="utf-8")
    assert "Evil&lt;b&gt;&amp;Co" in page and "Evil<b>" not in page
    assert "3.15 win-arm64, 3.15 win-amd64" in page
    assert '<a href="../p/cryptography/">cryptography</a>' in page
    assert '<a href="https://pypi.org/project/old-pkg/">Old_Pkg</a>' in page
    assert "built from source" in page
    assert "couldn&#x27;t install" in page or "couldn't install" in page
    assert build_new_wheels.CSP in page and "<script" not in page
    assert page.index("Evil") < page.index("Old_Pkg")  # newest first

    # Check global Atom feed
    root = ET.parse(site / "new.xml").getroot()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)
    titles = [e.findtext("a:title", namespaces=ns) for e in entries]
    assert titles == [
        "Evil<b>&Co 2.0 gained 3.15 win-arm64, 3.15 win-amd64",
        "cryptography 46.0.4 gained 3.15 win-arm64",
        "Old_Pkg 4.0 gained 3.15 linux-x86_64",
    ]
    assert root.findtext("a:updated", namespaces=ns) == "2026-11-17T00:00:00Z"

    # Check per-platform feed (win-arm64.xml)
    win_root = ET.parse(site / "new" / "win-arm64.xml").getroot()
    win_entries = win_root.findall("a:entry", ns)
    win_titles = [e.findtext("a:title", namespaces=ns) for e in win_entries]
    # Old_Pkg only gained linux-x86_64, so it should not appear in win-arm64
    assert win_titles == [
        "Evil<b>&Co 2.0 gained 3.15 win-arm64",
        "cryptography 46.0.4 gained 3.15 win-arm64",
    ]

    # Check sitemap
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    assert f"<loc>{build_new_wheels.BASE_URL}new/</loc>" in sitemap


def test_page_without_changes_or_file(tmp_path):
    site = tmp_path / "site"
    assert build_new_wheels.build(tmp_path / "missing.json", write_coverage(tmp_path, []), site) == 0
    assert "No new wheels recorded yet." in (site / "new" / "index.html").read_text(encoding="utf-8")
    ET.parse(site / "new.xml")
    for platform in build_pages.PLATFORM_NAMES:
        ET.parse(site / "new" / f"{platform}.xml")


def test_feed_ids_stay_unique_when_a_release_gains_targets_on_two_nights(tmp_path):
    changes = [
        {"date": "2026-11-16", "lost": [], "gained": [
            {"name": "pkg", "version": "1.0", "target": "3.14 win-arm64", "from": "source", "to": "wheel"},
        ]},
        {"date": "2026-11-17", "lost": [], "gained": [
            {"name": "pkg", "version": "1.0", "target": "3.14t win-arm64", "from": "source", "to": "wheel"},
        ]},
    ]
    changes_path = tmp_path / "changes.json"
    changes_path.write_text(json.dumps(changes), encoding="utf-8")
    site = tmp_path / "site"
    build_new_wheels.build(changes_path, write_coverage(tmp_path, ["pkg"]), site)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for path in (site / "new.xml", site / "new" / "win-arm64.xml"):
        ids = [e.findtext("a:id", namespaces=ns) for e in ET.parse(path).getroot().findall("a:entry", ns)]
        assert len(ids) == 2 and len(set(ids)) == 2, path
        assert ids[0].startswith(f"{build_new_wheels.BASE_URL}new/#2026-11-17-pkg-1.0")


def test_new_wheels_social_card():
    page = build_new_wheels.page([], set())
    assert '<meta property="og:title" content="New wheels · wheelgap tracker">' in page
    assert f'<meta property="og:url" content="{build_new_wheels.BASE_URL}new/">' in page
    assert '<meta name="twitter:card" content="summary_large_image">' in page


def test_home_page_footer_links_the_new_wheels_page():
    home = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text(encoding="utf-8")
    assert '<a href="new/">New wheels</a>' in home.split("<footer", 1)[1]
