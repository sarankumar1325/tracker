"""badge/<name>-tree.json (#94): whole-tree install coverage as a shields.io endpoint badge."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_badges, build_pages

NATIVE = ["linux-x86_64", "linux-aarch64", "macos-arm64", "macos-x86_64"]


def targets(pythons=("3.14",), platforms=NATIVE):
    return [{"label": f"{py} {pl}", "python": py, "platform": pl} for py in pythons for pl in platforms]


def package(name, install=None, rank=1, n=None, error=None):
    p = {"rank": rank, "name": name, "version": "1.0", "pure": False, "error": error, "results": ["wheel"] * (n or 4)}
    if install is not None:
        p["install"] = {label: {"status": status, "blockers": []} for label, status in install.items()}
    return p


def statuses(*values, python="3.14", platforms=NATIVE):
    return {f"{python} {pl}": v for pl, v in zip(platforms, values, strict=True)}


class TreeBadgeTests(unittest.TestCase):
    def badge(self, install, ts=None, **kw):
        return build_badges.tree_badge_for(package("demo", install, **kw), ts or targets())

    def test_counts_platforms_where_the_whole_tree_has_wheels(self):
        badge = self.badge(statuses("wheel", "wheel", "source", "missing"))
        self.assertEqual(badge["label"], "wheels+deps py3.14")
        self.assertEqual((badge["message"], badge["color"]), ("2/4 checked", "yellow"))
        self.assertEqual(badge["schemaVersion"], 1)
        self.assertEqual(badge["cacheSeconds"], build_badges.CACHE_SECONDS)

    def test_colours_follow_the_package_badge(self):
        self.assertEqual(self.badge(statuses(*["wheel"] * 4))["color"], "brightgreen")
        self.assertEqual(self.badge(statuses("wheel", "wheel", "wheel", "source"))["color"], "green")
        self.assertEqual(self.badge(statuses("wheel", "source", "source", "source"))["color"], "orange")
        self.assertEqual(self.badge(statuses(*["source"] * 4))["color"], "red")

    def test_any_not_checked_target_is_grey_partly_checked(self):
        badge = self.badge(statuses("wheel", "wheel", "wheel", "not_checked"))
        self.assertEqual((badge["message"], badge["color"]), ("partly checked", "lightgrey"))

    def test_no_install_data_no_badge(self):
        self.assertIsNone(self.badge(None))
        self.assertIsNone(self.badge(statuses(*["wheel"] * 4), error="lookup failed"))

    def test_pyodide_and_free_threaded_targets_dont_count(self):
        ts = targets(("3.14", "3.14t"), NATIVE + ["pyodide"])
        install = {**statuses(*["wheel"] * 4), **statuses(*["source"] * 4, python="3.14t"), "3.14 pyodide": "source"}
        self.assertEqual(self.badge(install, ts)["message"], "4/4 checked")

    def test_uses_the_newest_python_with_install_data(self):
        ts = targets(("3.14", "3.15"))
        badge = self.badge(statuses("wheel", "source", "wheel", "wheel"), ts)  # only 3.14 was install-checked
        self.assertEqual((badge["label"], badge["message"]), ("wheels+deps py3.14", "3/4 checked"))

    def test_a_newer_python_with_only_not_checked_install_results_is_skipped(self):
        # The scan has 3.15 targets and `install` has 3.15 labels, all not_checked: the badge is for 3.14, as
        # build_pages' summary is, not a grey "partly checked" for 3.15.
        six = NATIVE + ["win-arm64", "musl-aarch64"]  # the install scan's native platforms on 3.14
        ts = targets(("3.14", "3.15"), six)
        install = {
            **statuses("wheel", "wheel", "wheel", "wheel", "wheel", "source", platforms=six),
            **statuses(*["not_checked"] * 6, python="3.15", platforms=six),
        }
        badge = self.badge(install, ts)
        self.assertEqual((badge["label"], badge["message"]), ("wheels+deps py3.14", "5/6 checked"))
        self.assertEqual(badge["color"], "green")
        self.assertIn("on Python 3.14:", build_pages.describe_install(package("demo", install), ts))

    def test_only_not_checked_results_no_badge(self):
        self.assertIsNone(self.badge(statuses(*["not_checked"] * 4)))

    def test_one_platform(self):
        badge = self.badge({"3.14 linux-x86_64": "wheel"})
        self.assertEqual(badge["message"], "1/1 checked")


class BuildTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def coverage(self, packages):
        path = self.root / "coverage.json"
        scan = {"schema": 1, "generated": "2026-11-16T03:20:00+00:00", "wheelgap": "0.12.0", "targets": targets()}
        path.write_text(json.dumps(scan | {"packages": packages}), encoding="utf-8")
        return path

    def test_build_writes_tree_badges_only_for_packages_with_install_data(self):
        out = self.root / "badge"
        demo = package("Demo_Pkg", statuses("wheel", "wheel", "wheel", "source"))
        path = self.coverage([demo, package("older", rank=2)])
        self.assertEqual(build_badges.build(path, out), 2)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["demo-pkg-tree.json", "demo-pkg.json", "older.json"])
        tree = json.loads((out / "demo-pkg-tree.json").read_text(encoding="utf-8"))
        self.assertEqual(tree["message"], "3/4 checked")
        self.assertEqual(json.loads((out / "demo-pkg.json").read_text(encoding="utf-8"))["message"], "4/4 platforms")

    def test_a_package_named_like_a_tree_badge_keeps_its_own_badge(self):
        out = self.root / "badge"
        path = self.coverage([package("foo", statuses(*["source"] * 4)), package("foo-tree", rank=2)])
        build_badges.build(path, out)
        self.assertEqual(json.loads((out / "foo-tree.json").read_text(encoding="utf-8"))["label"], "wheels py3.14")
        self.assertEqual(build_badges.tree_badges(json.loads(path.read_text(encoding="utf-8"))), {})

    def test_package_page_shows_the_tree_snippet_when_there_is_a_tree_badge(self):
        site = self.root / "site"
        path = self.coverage([package("demo", statuses(*["wheel"] * 4)), package("older", rank=2)])
        build_pages.build(path, site, root=self.root)
        page = (site / "p" / "demo" / "index.html").read_text(encoding="utf-8")
        older = (site / "p" / "older" / "index.html").read_text(encoding="utf-8")
        tree = "https://img.shields.io/endpoint?url=https://wheelgap.github.io/tracker/badge/demo-tree.json"
        self.assertIn(tree, page)
        self.assertIn("badge/demo.json", page)
        self.assertNotIn("-tree.json", older)
        self.assertIn("badge/older.json", older)


if __name__ == "__main__":
    unittest.main()
