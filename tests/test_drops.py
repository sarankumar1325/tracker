"""Dropped platforms (#75): the nightly comparison, the waiting list, and the page and feed."""

import json
import re
import xml.etree.ElementTree as ET

import pytest

from scripts import build_drops, update_drops

LABELS = ["3.14 linux-x86_64", "3.14 win-amd64", "3.14 win-arm64"]


def scan(packages, generated="2026-11-16T03:20:00+00:00", wheelgap="0.12.0", labels=LABELS):
    return {"schema": 1, "generated": generated, "wheelgap": wheelgap,
            "targets": [{"label": label} for label in labels],
            "packages": [{"name": n, "version": v, "error": None, "results": list(r)} for n, v, r in packages]}


def night(tmp_path, old, new):
    (tmp_path / "previous.json").write_text(json.dumps(old), encoding="utf-8")
    (tmp_path / "coverage.json").write_text(json.dumps(new), encoding="utf-8")
    result = update_drops.update(tmp_path / "previous.json", tmp_path / "coverage.json", tmp_path / "drops.json")
    return result, json.loads((tmp_path / "drops.json").read_text(encoding="utf-8")) if (tmp_path / "drops.json").exists() else None


W, S, M, U = "wheel", "source", "missing", "unknown"


def test_a_new_release_without_a_platforms_wheel_is_a_drop(tmp_path):
    old = scan([("cryptography", "46.0.3", [W, W, W]), ("numpy", "2.3.0", [W, W, S])])
    new = scan([("cryptography", "46.0.4", [W, W, S]), ("numpy", "2.3.0", [W, W, S])])
    fresh, state = night(tmp_path, old, new)
    assert fresh == [{"date": "2026-11-16", "name": "cryptography", "from": "46.0.3", "version": "46.0.4",
                      "target": "3.14 win-arm64"}]
    assert state == {"schema": 1, "drops": fresh, "waiting": []}


def test_no_change_and_a_newly_added_target_are_not_drops(tmp_path):
    old = scan([("same", "1.0", [W, W, S]), ("bumped", "1.0", [W, S, S]), ("gains", "1.0", [W, S, M])])
    new = scan([("same", "1.0", [W, W, S]), ("bumped", "1.1", [W, S, S]), ("gains", "1.1", [W, W, W])])
    fresh, state = night(tmp_path, old, new)
    assert fresh == [] and state["drops"] == []


def test_unknown_cells_and_targets_only_one_scan_has_are_skipped(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])])
    new = scan([("pkg", "1.1", [U, W])], labels=["3.14 linux-x86_64", "3.14 win-amd64"])
    fresh, _ = night(tmp_path, old, new)
    assert fresh == []  # linux is unknown tonight, win-arm64 isn't scanned any more


def test_upload_in_progress_waits_then_counts_once_wheels_appear(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])])
    new = scan([("pkg", "1.1", [S, S, S])])
    fresh, state = night(tmp_path, old, new)
    assert fresh == [] and state["drops"] == []
    assert state["waiting"] == [{"name": "pkg", "from": "1.0", "version": "1.1",
                                 "wheels": LABELS, "since": "2026-11-16"}]
    # Next night: the wheels are up, but not win-arm64's. Compared with 1.0, not with last night's 1.1.
    later = scan([("pkg", "1.1", [W, W, S])], generated="2026-11-17T03:20:00+00:00")
    fresh, state = night(tmp_path, new, later)
    assert [(d["from"], d["version"], d["target"], d["date"]) for d in fresh] == [
        ("1.0", "1.1", "3.14 win-arm64", "2026-11-17")]
    assert state["waiting"] == []


def test_upload_in_progress_that_completes_with_everything_is_no_drop(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])])
    new = scan([("pkg", "1.1", [M, M, M])])
    night(tmp_path, old, new)
    fresh, state = night(tmp_path, new, scan([("pkg", "1.1", [W, W, W])], generated="2026-11-17T03:20:00+00:00"))
    assert fresh == [] and state == {"schema": 1, "drops": [], "waiting": []}


def test_a_release_that_never_gets_a_wheel_counts_after_the_wait(tmp_path):
    old = scan([("pkg", "1.0", [W, S, W])])
    new = scan([("pkg", "1.1", [S, S, M])])
    night(tmp_path, old, new)
    still = scan([("pkg", "1.1", [S, S, M])], generated="2026-11-20T03:20:00+00:00")
    fresh, state = night(tmp_path, new, still)
    assert fresh == [] and len(state["waiting"]) == 1
    done = scan([("pkg", "1.1", [S, S, M])], generated="2026-11-23T03:20:00+00:00")
    fresh, state = night(tmp_path, still, done)
    assert [d["target"] for d in fresh] == ["3.14 linux-x86_64", "3.14 win-arm64"]
    assert state["waiting"] == []


def test_a_yanked_release_is_taken_off_the_list(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])])
    new = scan([("pkg", "1.1", [W, W, S])])
    fresh, state = night(tmp_path, old, new)
    assert len(fresh) == 1
    # 1.1 is yanked: the current release is 1.0 again.
    back = scan([("pkg", "1.0", [W, W, W])], generated="2026-11-17T03:20:00+00:00")
    fresh, state = night(tmp_path, new, back)
    assert fresh == [] and state["drops"] == []


def test_a_yanked_release_stops_waiting(tmp_path):
    old = scan([("pkg", "2.0", [W, W, W])])
    new = scan([("pkg", "2.1", [S, S, S])])
    night(tmp_path, old, new)
    fresh, state = night(tmp_path, new, scan([("pkg", "2.0", [W, W, W])], generated="2026-11-17T03:20:00+00:00"))
    assert fresh == [] and state["waiting"] == [] and state["drops"] == []


def test_another_wheelgap_version_or_no_previous_scan_records_nothing(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])], wheelgap="0.11.0")
    new = scan([("pkg", "1.1", [W, W, S])])
    result, state = night(tmp_path, old, new)
    assert "wheelgap 0.11.0 -> 0.12.0" in result and state is None
    (tmp_path / "coverage.json").write_text(json.dumps(new), encoding="utf-8")
    result = update_drops.update(tmp_path / "nope.json", tmp_path / "coverage.json", tmp_path / "drops.json")
    assert result.startswith("no ")


def test_a_second_scan_the_same_day_adds_nothing_twice_and_old_drops_age_out(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])])
    new = scan([("pkg", "1.1", [W, W, S])])
    night(tmp_path, old, new)
    fresh, state = night(tmp_path, old, new)
    assert fresh == [] and len(state["drops"]) == 1
    year_later = scan([("other", "2", [W, W, S])], generated="2027-11-16T03:20:00+00:00")
    _, state = night(tmp_path, scan([("other", "1", [W, W, W])], generated="2027-11-15T03:20:00+00:00"), year_later)
    assert [d["name"] for d in state["drops"]] == ["other"]


def test_drops_are_newest_first(tmp_path):
    night(tmp_path, scan([("a", "1", [W, W, W])]), scan([("a", "2", [W, S, W])]))
    _, state = night(tmp_path, scan([("b", "1", [W, W, W])], generated="2026-11-17T03:20:00+00:00"),
                     scan([("b", "2", [S, W, W])], generated="2026-11-17T03:20:00+00:00"))
    assert [(d["date"], d["name"]) for d in state["drops"]] == [("2026-11-17", "b"), ("2026-11-16", "a")]


@pytest.mark.parametrize("old, new, back", [("1.0", "1.1", False), ("1.10", "1.9", True), ("2.0", "2.0.1", False),
                                           ("2.0.0", "2", False), ("1.0rc1", "0.9", True), ("x", "y", False)])
def test_went_back(old, new, back):
    assert update_drops.went_back(old, new) is back


def test_page_and_feed(tmp_path):
    drops = {"schema": 1, "waiting": [{"name": "w"}], "drops": [
        {"date": "2026-11-17", "name": "Evil<b>&Co", "from": "1", "version": "2", "target": "3.14 win-arm64"},
        {"date": "2026-11-17", "name": "Evil<b>&Co", "from": "1", "version": "2", "target": "3.14 win-amd64"},
        {"date": "2026-11-16", "name": "cryptography", "from": "46.0.3", "version": "46.0.4", "target": "3.14 win-arm64"},
    ]}
    (tmp_path / "drops.json").write_text(json.dumps(drops), encoding="utf-8")
    site = tmp_path / "site"
    assert build_drops.build(tmp_path / "drops.json", site) == 2
    page = (site / "drops" / "index.html").read_text(encoding="utf-8")
    assert "Evil&lt;b&gt;&amp;Co" in page and "Evil<b>" not in page
    assert "3.14 win-arm64, 3.14 win-amd64" in page
    assert '<a href="../p/cryptography/">cryptography</a>' in page and "46.0.3 → <strong>46.0.4</strong>" in page
    assert "1 new release with no wheel yet" in page
    assert build_drops.CSP in page and "<script" not in page
    assert page.index("Evil") < page.index("cryptography")  # newest first
    root = ET.parse(site / "drops.xml").getroot()  # well-formed XML
    ns = {"a": "http://www.w3.org/2005/Atom"}
    titles = [e.findtext("a:title", namespaces=ns) for e in root.findall("a:entry", ns)]
    assert titles == ["Evil<b>&Co 2 dropped 3.14 win-arm64, 3.14 win-amd64",
                      "cryptography 46.0.4 dropped 3.14 win-arm64"]
    assert root.findtext("a:updated", namespaces=ns) == "2026-11-17T00:00:00Z"
    ids = [e.findtext("a:id", namespaces=ns) for e in root.findall("a:entry", ns)]
    assert len(set(ids)) == len(ids)
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    assert "<loc>https://wheelgap.github.io/tracker/drops/</loc>" in sitemap


def test_page_without_drops_or_file(tmp_path):
    site = tmp_path / "site"
    assert build_drops.build(tmp_path / "missing.json", site) == 0
    assert "No drops recorded yet." in (site / "drops" / "index.html").read_text(encoding="utf-8")
    ET.parse(site / "drops.xml")


def test_home_page_footer_links_the_drops_page():
    from pathlib import Path

    home = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text(encoding="utf-8")
    assert '<a href="drops/">Dropped platforms</a>' in home.split("<footer", 1)[1]
