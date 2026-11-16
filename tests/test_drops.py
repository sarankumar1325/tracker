"""Dropped platforms (#75): the nightly comparison, the waiting list, and the page and feed."""

import json
import xml.etree.ElementTree as ET

import pytest

from scripts import build_drops, update_drops

LABELS = ["3.14 linux-x86_64", "3.14 win-amd64", "3.14 win-arm64"]
PY_LABELS = ["3.13 linux-x86_64", "3.13 win-amd64", "3.14 linux-x86_64", "3.14 win-amd64"]
PYODIDE_LABELS = ["3.14 linux-x86_64", "3.14 pyodide"]
LOCK_314 = {"python": "3.14", "pyodide_version": "?", "source": "pyodide/314.0.7-pyodide-lock.json"}


def at(day, time="03:20"):
    """The `generated` time of a scan on 2026-11-<day>."""
    return f"2026-11-{day:02d}T{time}:00+00:00"


def target(label, **changes):
    python, platform = label.split(" ")
    return {"label": label, "python": python, "platform": platform, "glibc": "2.36", "musl": "1.2", "macos": "14.0",
            **changes}


def scan(packages, generated=at(16), wheelgap="0.12.0", labels=LABELS, targets=None, locks=None):
    return {"schema": 1, "generated": generated, "wheelgap": wheelgap,
            "targets": targets or [target(label) for label in labels],
            "pyodide_locks": [LOCK_314] if locks is None else locks,
            "packages": [{"name": n, "version": v, "error": None, "results": list(r)} for n, v, r in packages]}


def night(tmp_path, old, new):
    (tmp_path / "previous.json").write_text(json.dumps(old), encoding="utf-8")
    (tmp_path / "coverage.json").write_text(json.dumps(new), encoding="utf-8")
    result = update_drops.update(tmp_path / "previous.json", tmp_path / "coverage.json", tmp_path / "drops.json")
    return result, json.loads((tmp_path / "drops.json").read_text(encoding="utf-8")) if (tmp_path / "drops.json").exists() else None


def nights(tmp_path, *scans):
    """Run the nightly comparison over consecutive scans; return the last night's (fresh, state)."""
    out = None
    for old, new in zip(scans, scans[1:]):
        out = night(tmp_path, old, new)
    return out


W, S, M, U, B = "wheel", "source", "missing", "unknown", "bundled"


def test_a_drop_is_held_one_night_and_published_when_the_next_scan_confirms_it(tmp_path):
    old = scan([("cryptography", "46.0.3", [W, W, W]), ("numpy", "2.3.0", [W, W, S])], generated=at(15))
    new = scan([("cryptography", "46.0.4", [W, W, S]), ("numpy", "2.3.0", [W, W, S])], generated=at(16))
    fresh, state = night(tmp_path, old, new)
    assert fresh == [] and state["drops"] == []
    assert state["waiting"] == [{"name": "cryptography", "from": "46.0.3", "version": "46.0.4",
                                 "targets": ["3.14 win-arm64"], "since": at(16)}]
    confirmed = scan([("cryptography", "46.0.4", [W, W, S]), ("numpy", "2.3.0", [W, W, S])], generated=at(17))
    fresh, state = night(tmp_path, new, confirmed)
    assert fresh == [{"date": "2026-11-17", "name": "cryptography", "from": "46.0.3", "version": "46.0.4",
                      "target": "3.14 win-arm64"}]
    assert state == {"schema": 1, "wheelgap": "0.12.0", "drops": fresh, "waiting": []}


def test_a_partial_upload_that_completes_the_next_night_is_no_drop(tmp_path):
    # The Linux wheel is up, the Windows jobs are still uploading when the scan runs.
    fresh, state = nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)),
                          scan([("pkg", "1.1", [W, S, M])], generated=at(16)),
                          scan([("pkg", "1.1", [W, W, W])], generated=at(17)))
    assert fresh == [] and state == {"schema": 1, "wheelgap": "0.12.0", "drops": [], "waiting": []}


def test_a_partial_upload_that_does_not_complete_is_a_drop_for_what_is_still_missing(tmp_path):
    fresh, state = nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)),
                          scan([("pkg", "1.1", [W, S, M])], generated=at(16)),
                          scan([("pkg", "1.1", [W, W, M])], generated=at(17)))
    assert [(d["date"], d["from"], d["version"], d["target"]) for d in fresh] == [
        ("2026-11-17", "1.0", "1.1", "3.14 win-arm64")]
    assert state["waiting"] == []


def test_a_wheel_uploaded_after_the_drop_was_published_withdraws_it(tmp_path):
    fresh, state = nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)),
                          scan([("pkg", "1.1", [W, W, M])], generated=at(16)),
                          scan([("pkg", "1.1", [W, W, M])], generated=at(17)))
    assert [d["target"] for d in state["drops"]] == ["3.14 win-arm64"]
    # The win-arm64 wheel turns up days later: the drop goes, and nothing else changes.
    fresh, state = night(tmp_path, scan([("pkg", "1.1", [W, W, M])], generated=at(17)),
                         scan([("pkg", "1.1", [W, W, W])], generated=at(19)))
    assert fresh == [] and state["drops"] == [] and state["waiting"] == []


def test_a_second_scan_the_same_night_is_not_a_later_scan(tmp_path):
    first = scan([("pkg", "1.1", [W, W, S])], generated=at(16))
    fresh, state = nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)), first,
                          scan([("pkg", "1.1", [W, W, S])], generated=at(16, "15:00")))
    assert fresh == [] and state["drops"] == []
    assert state["waiting"][0]["since"] == at(16)  # still the night it was first seen
    fresh, state = night(tmp_path, first, scan([("pkg", "1.1", [W, W, S])], generated=at(17)))
    assert [d["target"] for d in fresh] == ["3.14 win-arm64"]


def test_no_change_and_a_newly_added_target_are_not_drops(tmp_path):
    old = scan([("same", "1.0", [W, W, S]), ("bumped", "1.0", [W, S, S]), ("gains", "1.0", [W, S, M])])
    new = scan([("same", "1.0", [W, W, S]), ("bumped", "1.1", [W, S, S]), ("gains", "1.1", [W, W, W])])
    fresh, state = night(tmp_path, old, new)
    assert fresh == [] and state["drops"] == [] and state["waiting"] == []


def test_unknown_cells_and_targets_only_one_scan_has_are_skipped(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])])
    new = scan([("pkg", "1.1", [U, W])], labels=["3.14 linux-x86_64", "3.14 win-amd64"])
    fresh, state = night(tmp_path, old, new)
    assert fresh == [] and state["waiting"] == []  # linux is unknown tonight, win-arm64 isn't scanned any more


def test_a_new_python_label_is_not_a_drop(tmp_path):
    new_labels = LABELS + ["3.15 linux-x86_64"]
    fresh, state = nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)),
                          scan([("pkg", "1.1", [W, W, W, S])], generated=at(16), labels=new_labels),
                          scan([("pkg", "1.1", [W, W, W, S])], generated=at(17), labels=new_labels))
    assert fresh == [] and state["drops"] == [] and state["waiting"] == []


def test_a_target_is_compared_only_when_its_whole_definition_is_unchanged(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])], generated=at(15))
    newer_glibc = [target(LABELS[0], glibc="2.39")] + [target(label) for label in LABELS[1:]]
    fresh, state = night(tmp_path, old, scan([("pkg", "1.1", [S, W, W])], generated=at(16), targets=newer_glibc))
    assert fresh == [] and state["waiting"] == []  # "3.14 linux-x86_64" means another glibc tonight
    # A held candidate whose target changes before it's confirmed isn't published either.
    held = scan([("pkg", "1.1", [S, W, W])], generated=at(16))
    night(tmp_path, old, held)
    fresh, state = night(tmp_path, held, scan([("pkg", "1.1", [S, W, W])], generated=at(17), targets=newer_glibc))
    assert fresh == [] and state["drops"] == [] and state["waiting"] == []


def test_a_pyodide_target_is_compared_only_with_the_same_pyodide_lock(tmp_path):
    old = scan([("pkg", "1.0", [W, W])], generated=at(15), labels=PYODIDE_LABELS)
    newer_lock = [dict(LOCK_314, source="pyodide/314.0.8-pyodide-lock.json")]
    fresh, state = night(tmp_path, old, scan([("pkg", "1.1", [W, M])], generated=at(16), labels=PYODIDE_LABELS,
                                             locks=newer_lock))
    assert fresh == [] and state["waiting"] == []
    # With the same lock, it's compared as any other target.
    fresh, state = nights(tmp_path, old, scan([("pkg", "1.1", [W, M])], generated=at(16), labels=PYODIDE_LABELS),
                          scan([("pkg", "1.1", [W, M])], generated=at(17), labels=PYODIDE_LABELS))
    assert [d["target"] for d in fresh] == ["3.14 pyodide"]


def test_wheel_to_bundled_and_back_is_not_a_drop(tmp_path):
    fresh, state = nights(tmp_path, scan([("a", "1.0", [W, W]), ("b", "1.0", [W, B])], generated=at(15),
                                         labels=PYODIDE_LABELS),
                          scan([("a", "1.1", [W, B]), ("b", "1.1", [W, W])], generated=at(16), labels=PYODIDE_LABELS),
                          scan([("a", "1.1", [W, B]), ("b", "1.1", [W, W])], generated=at(17), labels=PYODIDE_LABELS))
    assert fresh == [] and state["drops"] == [] and state["waiting"] == []


def test_a_release_that_ends_support_for_a_python_is_not_a_platform_drop(tmp_path):
    old = scan([("ends313", "1.0", [W, W, W, W]), ("mixed", "1.0", [W, W, W, W]), ("partial313", "1.0", [W, W, W, W])],
               generated=at(15), labels=PY_LABELS)
    new = [("ends313", "2.0", [S, M, W, W]),  # every 3.13 target goes at once: Python 3.13 support ended
           ("mixed", "2.0", [S, S, W, S]),  # 3.13 ended, and 3.14 also lost win-amd64: that one is a drop
           ("partial313", "2.0", [W, S, W, W])]  # 3.13 still has a Linux wheel: Windows was dropped
    fresh, state = nights(tmp_path, old, scan(new, generated=at(16), labels=PY_LABELS),
                          scan(new, generated=at(17), labels=PY_LABELS))
    assert [(d["name"], d["target"]) for d in fresh] == [("mixed", "3.14 win-amd64"), ("partial313", "3.13 win-amd64")]
    assert state["waiting"] == []


def test_upload_in_progress_waits_then_counts_once_wheels_appear(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])], generated=at(15))
    new = scan([("pkg", "1.1", [S, S, S])], generated=at(16))
    fresh, state = night(tmp_path, old, new)
    assert fresh == [] and state["drops"] == []
    assert state["waiting"] == [{"name": "pkg", "from": "1.0", "version": "1.1", "targets": LABELS, "since": at(16)}]
    # Next night: the wheels are up, but not win-arm64's. Compared with 1.0, not with last night's 1.1.
    fresh, state = night(tmp_path, new, scan([("pkg", "1.1", [W, W, S])], generated=at(17)))
    assert [(d["from"], d["version"], d["target"], d["date"]) for d in fresh] == [
        ("1.0", "1.1", "3.14 win-arm64", "2026-11-17")]
    assert state["waiting"] == []


def test_upload_in_progress_that_completes_with_everything_is_no_drop(tmp_path):
    fresh, state = nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)),
                          scan([("pkg", "1.1", [M, M, M])], generated=at(16)),
                          scan([("pkg", "1.1", [W, W, W])], generated=at(17)))
    assert fresh == [] and state == {"schema": 1, "wheelgap": "0.12.0", "drops": [], "waiting": []}


def test_a_release_that_never_gets_a_wheel_counts_after_the_wait(tmp_path):
    old = scan([("pkg", "1.0", [W, S, W])], generated=at(15))
    new = scan([("pkg", "1.1", [S, S, M])], generated=at(16))
    night(tmp_path, old, new)
    still = scan([("pkg", "1.1", [S, S, M])], generated=at(20))
    fresh, state = night(tmp_path, new, still)
    assert fresh == [] and len(state["waiting"]) == 1
    done = scan([("pkg", "1.1", [S, S, M])], generated=at(23))
    fresh, state = night(tmp_path, still, done)
    assert [d["target"] for d in fresh] == ["3.14 linux-x86_64", "3.14 win-arm64"]
    assert state["waiting"] == []


def test_a_newer_release_while_one_waits_is_held_in_its_place(tmp_path):
    fresh, state = nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)),
                          scan([("pkg", "1.1", [W, W, S])], generated=at(16)),
                          scan([("pkg", "1.2", [W, W, S])], generated=at(17)))
    assert fresh == [] and state["waiting"] == [{"name": "pkg", "from": "1.0", "version": "1.2",
                                                 "targets": ["3.14 win-arm64"], "since": at(17)}]
    fresh, state = night(tmp_path, scan([("pkg", "1.2", [W, W, S])], generated=at(17)),
                         scan([("pkg", "1.2", [W, W, S])], generated=at(18)))
    assert [(d["from"], d["version"], d["target"]) for d in fresh] == [("1.0", "1.2", "3.14 win-arm64")]


def test_a_yanked_release_is_taken_off_the_list(tmp_path):
    new = scan([("pkg", "1.1", [W, W, S])], generated=at(17))
    fresh, state = nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)),
                          scan([("pkg", "1.1", [W, W, S])], generated=at(16)), new)
    assert len(fresh) == 1
    # 1.1 is yanked: the current release is 1.0 again.
    fresh, state = night(tmp_path, new, scan([("pkg", "1.0", [W, W, W])], generated=at(18)))
    assert fresh == [] and state["drops"] == []


def test_a_yanked_release_stops_waiting(tmp_path):
    fresh, state = nights(tmp_path, scan([("pkg", "2.0", [W, W, W])], generated=at(15)),
                          scan([("pkg", "2.1", [W, S, S])], generated=at(16)),
                          scan([("pkg", "2.0", [W, W, W])], generated=at(17)))
    assert fresh == [] and state["waiting"] == [] and state["drops"] == []


def test_a_package_entering_or_leaving_the_top_n(tmp_path):
    # Entering: no previous release to compare with.
    fresh, state = night(tmp_path, scan([("old", "1", [W, W, W])], generated=at(15)),
                         scan([("old", "1", [W, W, W]), ("newcomer", "1", [S, S, S])], generated=at(16)))
    assert fresh == [] and state["waiting"] == []
    # Leaving while it waits: it stops waiting, and isn't published when it comes back.
    left = scan([("old", "1", [W, W, W])], generated=at(18))
    fresh, state = nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(16)),
                          scan([("pkg", "1.1", [W, W, S])], generated=at(17)), left)
    assert fresh == [] and state["waiting"] == []
    fresh, state = night(tmp_path, left, scan([("pkg", "1.1", [W, W, S])], generated=at(19)))
    assert fresh == [] and state["drops"] == [] and state["waiting"] == []


def test_another_wheelgap_version_or_no_previous_scan_records_nothing(tmp_path):
    old = scan([("pkg", "1.0", [W, W, W])], wheelgap="0.11.0")
    new = scan([("pkg", "1.1", [W, W, S])])
    result, state = night(tmp_path, old, new)
    assert "wheelgap 0.11.0 -> 0.12.0" in result
    assert state == {"schema": 1, "wheelgap": "0.12.0", "drops": [], "waiting": []}
    (tmp_path / "coverage.json").write_text(json.dumps(new), encoding="utf-8")
    result = update_drops.update(tmp_path / "nope.json", tmp_path / "coverage.json", tmp_path / "drops.json")
    assert result.startswith("no ")


def test_waiting_is_cleared_across_a_wheelgap_bump(tmp_path):
    first = scan([("pkg", "1.1", [W, W, S])], generated=at(16))
    night(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)), first)
    bumped = scan([("pkg", "1.1", [W, W, S])], generated=at(17), wheelgap="0.13.0")
    result, state = night(tmp_path, first, bumped)
    assert isinstance(result, str) and state["waiting"] == [] and state["wheelgap"] == "0.13.0"
    fresh, state = night(tmp_path, bumped, scan([("pkg", "1.1", [W, W, S])], generated=at(18), wheelgap="0.13.0"))
    assert fresh == [] and state["drops"] == [] and state["waiting"] == []


def test_waiting_is_cleared_across_a_wheelgap_bump_even_if_that_night_was_not_recorded(tmp_path):
    night(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)), scan([("pkg", "1.1", [W, W, S])], generated=at(16)))
    # The bump night's step didn't run, so tonight's previous scan already has the new wheelgap.
    fresh, state = night(tmp_path, scan([("pkg", "1.1", [W, W, S])], generated=at(17), wheelgap="0.13.0"),
                         scan([("pkg", "1.1", [W, W, S])], generated=at(18), wheelgap="0.13.0"))
    assert fresh == [] and state["drops"] == [] and state["waiting"] == [] and state["wheelgap"] == "0.13.0"


def test_a_rerun_adds_nothing_twice_and_old_drops_age_out(tmp_path):
    held = scan([("pkg", "1.1", [W, W, S])], generated=at(16))
    confirmed = scan([("pkg", "1.1", [W, W, S])], generated=at(17))
    nights(tmp_path, scan([("pkg", "1.0", [W, W, W])], generated=at(15)), held, confirmed)
    fresh, state = night(tmp_path, held, confirmed)
    assert fresh == [] and len(state["drops"]) == 1
    _, state = nights(tmp_path, scan([("other", "1", [W, W, W])], generated="2027-11-15T03:20:00+00:00"),
                      scan([("other", "2", [W, W, S])], generated="2027-11-16T03:20:00+00:00"),
                      scan([("other", "2", [W, W, S])], generated="2027-11-17T03:20:00+00:00"))
    assert [d["name"] for d in state["drops"]] == ["other"]


def test_drops_are_newest_first(tmp_path):
    _, state = nights(tmp_path, scan([("a", "1", [W, W, W]), ("b", "1", [W, W, W])], generated=at(16)),
                      scan([("a", "2", [W, S, W]), ("b", "1", [W, W, W])], generated=at(17)),
                      scan([("a", "2", [W, S, W]), ("b", "2", [S, W, W])], generated=at(18)),
                      scan([("a", "2", [W, S, W]), ("b", "2", [S, W, W])], generated=at(19)))
    assert [(d["date"], d["name"]) for d in state["drops"]] == [("2026-11-19", "b"), ("2026-11-18", "a")]


@pytest.mark.parametrize("old, new, back", [("1.0", "1.1", False), ("1.10", "1.9", True), ("2.0", "2.0.1", False),
                                           ("2.0.0", "2", False), ("1.0rc1", "0.9", True), ("x", "y", False)])
def test_went_back(old, new, back):
    assert update_drops.went_back(old, new) is back


def write_coverage(tmp_path, names):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"packages": [{"name": n} for n in names]}), encoding="utf-8")
    return path


def test_page_and_feed(tmp_path):
    drops = {"schema": 1, "waiting": [{"name": "w"}], "drops": [
        {"date": "2026-11-17", "name": "Evil<b>&Co", "from": "1", "version": "2", "target": "3.14 win-arm64"},
        {"date": "2026-11-17", "name": "Evil<b>&Co", "from": "1", "version": "2", "target": "3.14 win-amd64"},
        {"date": "2026-11-16", "name": "cryptography", "from": "46.0.3", "version": "46.0.4", "target": "3.14 win-arm64"},
        {"date": "2026-11-15", "name": "Old_Pkg", "from": "3", "version": "4", "target": "3.14 win-arm64"},
    ]}
    (tmp_path / "drops.json").write_text(json.dumps(drops), encoding="utf-8")
    coverage = write_coverage(tmp_path, ["Evil<b>&Co", "Cryptography"])  # Old_Pkg has left the top N
    site = tmp_path / "site"
    assert build_drops.build(tmp_path / "drops.json", coverage, site) == 3
    page = (site / "drops" / "index.html").read_text(encoding="utf-8")
    assert "Evil&lt;b&gt;&amp;Co" in page and "Evil<b>" not in page
    assert "3.14 win-arm64, 3.14 win-amd64" in page
    assert '<a href="../p/cryptography/">cryptography</a>' in page and "46.0.3 → <strong>46.0.4</strong>" in page
    assert '<a href="https://pypi.org/project/old-pkg/">Old_Pkg</a>' in page
    assert "1 new release missing wheels" in page
    assert build_drops.CSP in page and "<script" not in page
    assert page.index("Evil") < page.index("cryptography") < page.index("Old_Pkg")  # newest first
    root = ET.parse(site / "drops.xml").getroot()  # well-formed XML
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)
    titles = [e.findtext("a:title", namespaces=ns) for e in entries]
    assert titles == ["Evil<b>&Co 2 dropped 3.14 win-arm64, 3.14 win-amd64",
                      "cryptography 46.0.4 dropped 3.14 win-arm64", "Old_Pkg 4 dropped 3.14 win-arm64"]
    assert root.findtext("a:updated", namespaces=ns) == "2026-11-17T00:00:00Z"
    base = "https://wheelgap.github.io/tracker/"
    ids = [e.findtext("a:id", namespaces=ns) for e in entries]
    assert ids[1:] == [f"{base}drops/#cryptography-46.0.4", f"{base}drops/#old-pkg-4"]  # canonical names
    links = [e.find("a:link", ns).get("href") for e in entries]
    assert links[1:] == [f"{base}p/cryptography/", "https://pypi.org/project/old-pkg/"]
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    assert f"<loc>{base}drops/</loc>" in sitemap


def test_page_without_drops_or_file(tmp_path):
    site = tmp_path / "site"
    assert build_drops.build(tmp_path / "missing.json", write_coverage(tmp_path, []), site) == 0
    assert "No drops recorded yet." in (site / "drops" / "index.html").read_text(encoding="utf-8")
    ET.parse(site / "drops.xml")


def test_home_page_footer_links_the_drops_page():
    from pathlib import Path

    home = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text(encoding="utf-8")
    assert '<a href="drops/">Dropped platforms</a>' in home.split("<footer", 1)[1]
