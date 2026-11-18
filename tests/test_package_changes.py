"""Tests for recent wheel changes on package pages (scripts/build_pages.py, #115)."""

import json


from scripts import build_pages, update_changes

TARGETS = [
    {"label": "3.14 win-arm64", "python": "3.14", "platform": "win-arm64"},
    {"label": "3.14 linux-x86_64", "python": "3.14", "platform": "linux-x86_64"},
    {"label": "3.13 musl-x86_64", "python": "3.13", "platform": "musl-x86_64"},
]


def make_package(name, rank=1, version="1.0.0", statuses=None):
    return {
        "rank": rank,
        "name": name,
        "version": version,
        "pure": False,
        "error": None,
        "results": statuses or ["wheel", "wheel", "wheel"],
    }


def make_scan(packages):
    return {
        "schema": 1,
        "wheelgap": "0.13.0",
        "generated": "2026-11-16T12:00:00Z",
        "targets": TARGETS,
        "packages": packages,
    }


def item(name, target, frm, to, version="1.0"):
    return {"name": name, "version": version, "target": target, "from": frm, "to": to}


def day(date, gained=(), lost=()):
    """One day of changes.json, as update_changes.py writes it."""
    return {"date": date, "gained": list(gained), "lost": list(lost)}


def test_format_target():
    assert build_pages.format_target("3.14 win-arm64") == "Windows ARM64, Python 3.14"
    assert build_pages.format_target("3.14 linux-x86_64") == "Linux x86_64, Python 3.14"
    assert build_pages.format_target("3.13 musl-x86_64") == "Alpine x86_64, Python 3.13"
    assert build_pages.format_target("3.13 pyodide") == "Pyodide (browser), Python 3.13"
    assert build_pages.format_target("3.14t win-arm64") == "Windows ARM64, Python 3.14t"


def test_changes_render_newest_first_with_target_formatting():
    pkg = make_package("demo")
    scan = make_scan([pkg])
    changes = build_pages.changes_by_package([
        day("2026-11-12", lost=[item("demo", "3.13 musl-x86_64", "wheel", "source")]),
        day("2026-11-16", gained=[item("demo", "3.14 win-arm64", "source", "wheel")]),
    ])["demo"]
    out = build_pages.page(pkg, scan, "3.14", changes=changes)

    assert '<section aria-labelledby="recent-changes">' in out
    assert '<h2 id="recent-changes">Recent changes</h2>' in out
    assert f"the log keeps {update_changes.KEEP_DAYS} days" in out
    pos_16 = out.index("2026-11-16: gained a wheel for Windows ARM64, Python 3.14")
    pos_12 = out.index("2026-11-12: lost a wheel for Alpine x86_64, Python 3.13")
    assert pos_16 < pos_12


def test_same_day_losses_come_before_gains():
    changes = build_pages.changes_by_package([
        day(
            "2026-11-16",
            gained=[item("demo", "3.14 win-arm64", "source", "wheel")],
            lost=[item("demo", "3.14 linux-x86_64", "wheel", "source")],
        ),
    ])["demo"]
    assert [(c["gained"], c["target"]) for c in changes] == [
        (False, "3.14 linux-x86_64"),
        (True, "3.14 win-arm64"),
    ]


def test_names_are_canonicalised():
    by_pkg = build_pages.changes_by_package(
        [day("2026-11-16", gained=[item("Pkg_One", "3.14 win-arm64", "source", "wheel")])]
    )
    assert list(by_pkg) == ["pkg-one"]


def test_empty_log_gives_no_section():
    pkg = make_package("demo")
    scan = make_scan([pkg])

    out_empty = build_pages.page(pkg, scan, "3.14", changes=[])
    assert 'aria-labelledby="recent-changes"' not in out_empty
    assert "Recent changes" not in out_empty

    out_none = build_pages.page(pkg, scan, "3.14", changes=None)
    assert 'aria-labelledby="recent-changes"' not in out_none
    assert "Recent changes" not in out_none


def test_capped_at_ten_entries():
    pkg = make_package("demo")
    scan = make_scan([pkg])
    changes = build_pages.changes_by_package([
        day(f"2026-11-{n:02d}", gained=[item("demo", "3.14 win-arm64", "source", "wheel")])
        for n in range(1, 16)
    ])["demo"]
    out = build_pages.page(pkg, scan, "3.14", changes=changes)

    assert out.count("gained a wheel for Windows ARM64, Python 3.14") == 10
    assert "2026-11-15:" in out
    assert "2026-11-06:" in out
    assert "2026-11-05:" not in out
    assert "<li>and 5 more</li>" in out


def test_package_isolation():
    pkg1 = make_package("pkg-one")
    pkg2 = make_package("pkg-two")
    scan = make_scan([pkg1, pkg2])

    raw_changes = [
        {
            "date": "2026-11-16",
            "gained": [
                {"name": "pkg-one", "target": "3.14 win-arm64", "to": "wheel", "version": "1.0"},
            ],
            "lost": [
                {"name": "pkg-two", "target": "3.13 musl-x86_64", "from": "wheel", "version": "2.0"},
            ],
        }
    ]

    by_pkg = build_pages.changes_by_package(raw_changes)
    out1 = build_pages.page(pkg1, scan, "3.14", changes=by_pkg.get("pkg-one"))
    out2 = build_pages.page(pkg2, scan, "3.14", changes=by_pkg.get("pkg-two"))

    assert "Windows ARM64, Python 3.14" in out1
    assert "Alpine x86_64, Python 3.13" not in out1

    assert "Alpine x86_64, Python 3.13" in out2
    assert "Windows ARM64, Python 3.14" not in out2


def test_changes_escapes_html():
    pkg = make_package("demo")
    scan = make_scan([pkg])
    changes = [{"date": "2026-11-16<tag>", "gained": True, "target": "3.14 <custom>"}]
    out = build_pages.page(pkg, scan, "3.14", changes=changes)

    assert "<tag>" not in out
    assert "&lt;tag&gt;" in out
    assert "<custom>" not in out
    assert "&lt;custom&gt;" in out


def test_build_integration_with_changes_json(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    site_dir = tmp_path / "_site"

    pkg1 = make_package("pkg-one")
    pkg2 = make_package("pkg-two")
    scan = make_scan([pkg1, pkg2])
    (data_dir / "coverage.json").write_text(json.dumps(scan), encoding="utf-8")

    changes_data = [
        {
            "date": "2026-11-16",
            "gained": [
                {"name": "pkg-one", "target": "3.14 win-arm64", "to": "wheel", "version": "1.0"},
            ],
            "lost": [],
        }
    ]
    (data_dir / "changes.json").write_text(json.dumps(changes_data), encoding="utf-8")

    count = build_pages.build(data_dir / "coverage.json", site_dir, notes_dir=None, root=tmp_path)
    assert count == 2

    page1_text = (site_dir / "p" / "pkg-one" / "index.html").read_text(encoding="utf-8")
    page2_text = (site_dir / "p" / "pkg-two" / "index.html").read_text(encoding="utf-8")

    assert '<section aria-labelledby="recent-changes">' in page1_text
    assert "2026-11-16: gained a wheel for Windows ARM64, Python 3.14" in page1_text

    assert '<section aria-labelledby="recent-changes">' not in page2_text
    assert "Recent changes" not in page2_text


# read_changes: the publish step keeps going on a malformed changes.json (#168).


def write(tmp_path, text):
    path = tmp_path / "changes.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_read_changes_missing_file_is_empty_without_warning(tmp_path, capsys):
    assert update_changes.read_changes(tmp_path / "changes.json") == []
    assert "::warning::" not in capsys.readouterr().out


def test_read_changes_invalid_json_or_not_a_list_is_empty_with_warning(tmp_path, capsys):
    for text in ("[{", '{"date": "2026-11-17"}', "null", ""):
        assert update_changes.read_changes(write(tmp_path, text)) == [], text
        assert "::warning::" in capsys.readouterr().out, text


def test_read_changes_drops_malformed_days_and_items(tmp_path, capsys):
    good = day("2026-11-16", gained=[item("a", "3.14 win-arm64", "source", "wheel")])
    data = [
        {"date": "2026-11-17"},  # no gained/lost
        {"date": "2026-11-17", "gained": None, "lost": []},
        None,
        {"date": "17 Nov", "gained": [], "lost": []},
        good,
        day("2026-11-18", gained=[None, {"name": "b"}, item("c", "3.14 win-arm64", "source", "wheel")], lost=[3]),
    ]
    got = update_changes.read_changes(write(tmp_path, json.dumps(data)))
    assert got == [good, day("2026-11-18", gained=[item("c", "3.14 win-arm64", "source", "wheel")])]
    assert "::warning::" in capsys.readouterr().out


def test_read_changes_keeps_a_valid_file_as_is(tmp_path, capsys):
    data = [
        day("2026-11-15", lost=[item("a", "3.14 win-arm64", "wheel", "source")]),
        day("2026-11-16", gained=[item("a", "3.14 win-arm64", "source", "wheel")]),
    ]
    assert update_changes.read_changes(write(tmp_path, json.dumps(data))) == data
    assert "::warning::" not in capsys.readouterr().out


def test_build_pages_survives_malformed_changes(tmp_path, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "coverage.json").write_text(json.dumps(make_scan([make_package("pkg-one")])), encoding="utf-8")
    for changes in (
        [{"date": "2026-11-17"}],
        [{"date": "2026-11-17", "gained": None, "lost": []}],
        {"date": "2026-11-17"},
        "not json",
    ):
        text = changes if isinstance(changes, str) else json.dumps(changes)
        (data_dir / "changes.json").write_text(text, encoding="utf-8")
        assert build_pages.build(data_dir / "coverage.json", tmp_path / "_site", notes_dir=None, root=tmp_path) == 1
        assert "::warning::" in capsys.readouterr().out
        assert (tmp_path / "_site" / "p" / "pkg-one" / "index.html").exists()
