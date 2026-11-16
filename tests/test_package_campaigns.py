"""Package pages: the campaigns that list the package, and its README badge snippet (#62)."""

import html
import json

from scripts import build_pages


def test_package_campaigns_and_badge(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    notes = tmp_path / "notes"
    notes.mkdir()
    targets = [
        {"label": f"{py} {pl}", "python": py, "platform": pl}
        for py in ("3.13", "3.14")
        for pl in ("linux-x86_64", "musl-aarch64")
    ]

    def pkg(name, rank, results):
        return dict(name=name, rank=rank, results=results, version="1.0", pure=False, error=None)

    scan = dict(schema=1, generated="2026-11-12", wheelgap="0.9", targets=targets, packages=[
        pkg("Todo_Pkg", 1, ["wheel", "source", "wheel", "wheel"]),
        pkg("aside", 2, ["wheel", "missing", "wheel", "wheel"]),
        pkg("os-gap", 3, ["source", "source", "wheel", "wheel"]),
        pkg("none", 4, ["wheel"] * 4),
        pkg("done", 6, ["wheel"] * 4),
        pkg("outside", 7, ["wheel", "source", "wheel", "wheel"]),
    ])
    coverage = data / "coverage.json"
    coverage.write_text(json.dumps(scan))
    title = 'Campaign <&" title'
    (tmp_path / "campaigns.toml").write_text(
        '[[campaign]]\nid="example"\nplatform="musl-aarch64"\ntop=4\n'
        'start="2026-11-10"\npython="3.13"\ntitle=' + json.dumps(title) + "\n"
    )
    baselines = data / "campaigns"
    baselines.mkdir()
    (baselines / "example.json").write_text(json.dumps(dict(
        schema=1, campaign="example", target="3.13 musl-aarch64", top=4,
        start="2026-11-10", recorded="2026-11-10",
        packages=[dict(name="done", status="source")],
    )))
    (notes / "aside.toml").write_text(
        '[[note]]\nplatforms=["musl-aarch64"]\nkind="alternative"\n'
        'text="Use another package."\nlinks=["https://example.com/"]\nupdated=2026-11-11\n'
    )
    site = tmp_path / "_site"
    assert build_pages.build(coverage, site, notes, root=tmp_path) == 6
    pages = {p: (site / "p" / p / "index.html").read_text()
             for p in ("todo-pkg", "aside", "done", "none", "os-gap", "outside")}
    link = f'<a href="../../campaigns/example/">{html.escape(title)}</a>'
    assert "On the to-do list of " + link in pages["todo-pkg"]
    assert "Set aside in " + link + " (has an alternative)" in pages["aside"]
    assert "Done in " + link in pages["done"]
    assert all("Campaigns:" not in pages[p] for p in ("none", "os-gap", "outside"))
    assert all(title not in page for page in pages.values())
    badge = ("[![wheels](https://img.shields.io/endpoint?url="
             "https://wheelgap.github.io/tracker/badge/todo-pkg.json)]"
             "(https://wheelgap.github.io/tracker/#package=Todo_Pkg)")
    assert "<pre" in pages["todo-pkg"] and html.escape(badge) in pages["todo-pkg"]
    assert 'href="../../data/packages/todo-pkg.json"' in pages["todo-pkg"]
    unsafe = dict(scan["packages"][0], name='<pkg&"')
    page = build_pages.page(unsafe, scan, "3.14")
    assert html.escape(unsafe["name"]) in page and unsafe["name"] not in page


def test_package_page_follows_a_new_python_campaign(tmp_path):
    """#103: build_pages passes compare to todo_lists, so a package page agrees with its new-Python campaign."""
    data = tmp_path / "data"
    data.mkdir()
    targets = [
        {"label": f"{py} {pl}", "python": py, "platform": pl}
        for py in ("3.14", "3.15")
        for pl in ("linux-x86_64", "musl-aarch64")
    ]

    def pkg(name, rank, results):
        return dict(name=name, rank=rank, results=results, version="1.0", pure=False, error=None)

    scan = dict(schema=1, generated="2026-11-17", wheelgap="0.9", targets=targets, packages=[
        # A 3.14 linux-x86_64 wheel but none for 3.15 yet: to do for the new-Python campaign. Under the
        # platform rule it would be left out (no 3.15 wheel on any Linux platform).
        pkg("waiting", 1, ["wheel", "wheel", "source", "source"]),
        # No linux-x86_64 wheel for 3.14 either: not a new-Python gap. Under the platform rule it would be
        # to do (a 3.15 musl-aarch64 wheel).
        pkg("never", 2, ["source", "wheel", "source", "wheel"]),
        pkg("ready", 3, ["wheel"] * 4),
    ])
    coverage = data / "coverage.json"
    coverage.write_text(json.dumps(scan))
    (tmp_path / "campaigns.toml").write_text(
        '[[campaign]]\nid="py315"\ntitle="Python 3.15"\nplatform="linux-x86_64"\ntop=3\n'
        'start="2026-11-17"\npython="3.15"\ncompare="python"\n'
    )
    site = tmp_path / "_site"
    notes = tmp_path / "notes"
    notes.mkdir()
    assert build_pages.build(coverage, site, notes, root=tmp_path) == 3
    pages = {p: (site / "p" / p / "index.html").read_text() for p in ("waiting", "never", "ready")}
    link = '<a href="../../campaigns/py315/">Python 3.15</a>'
    assert "On the to-do list of " + link in pages["waiting"]
    assert "Campaigns:" not in pages["never"]
    assert "Campaigns:" not in pages["ready"]
