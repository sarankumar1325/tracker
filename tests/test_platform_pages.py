"""Offline regression tests for crawlable platform pages (#111)."""

import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_lab, build_pages, build_platform_pages

# Declared lab coverage for these tests. The musl entry's "platform" is the interpreter's (linux-aarch64), which must
# not count as lab coverage for Linux ARM64.
LAB = {
    "3.15 win-arm64": {"runner": "r", "python": "3.15", "platform": "win-arm64", "wheel": "win_arm64"},
    "3.14 musl-aarch64": {"runner": "r", "python": "3.14", "platform": "linux-aarch64", "wheel": "x"},
}


class PlatformPageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.site = self.root / "_site"
        self.site.mkdir()
        (self.site / "sitemap.xml").write_text(
            '<?xml version="1.0"?><urlset><url><loc>https://wheelgap.github.io/tracker/</loc></url></urlset>',
            encoding="utf-8",
        )
        # Pyodide has no target for the newest Python (3.15), so its page uses 3.14.
        self.scan = {
            "schema": 1,
            "generated": "2026-11-17T03:00:00+00:00",
            "wheelgap": "0.13.0",
            "targets": [
                {"label": "3.15 win-arm64", "python": "3.15", "platform": "win-arm64"},
                {"label": "3.15 linux-x86_64", "python": "3.15", "platform": "linux-x86_64"},
                {"label": "3.14 pyodide", "python": "3.14", "platform": "pyodide"},
                {"label": "3.15t win-arm64", "python": "3.15t", "platform": "win-arm64"},
                {"label": "3.15 linux-aarch64", "python": "3.15", "platform": "linux-aarch64"},
            ],
            "packages": [
                {
                    "name": "Typing_Extensions",
                    "rank": 1,
                    "version": "4.0",
                    "error": None,
                    "results": ["source", "wheel", "bundled", "source", "wheel"],
                },
                {
                    "name": "sample",
                    "rank": 2,
                    "version": "1.1",
                    "error": None,
                    "results": ["missing", "wheel", "wheel", "missing", "wheel"],
                },
                {
                    "name": "evil",
                    "rank": 3,
                    "version": "<b>&",
                    "error": None,
                    "results": ["missing", "wheel", "missing", "missing", "wheel"],
                },
            ],
        }
        evil = {"name": "evil", "version": "<b>&", "rank": 3, "status": "missing"}
        self.wanted = {
            "generated": self.scan["generated"],
            "targets": {
                "3.15 win-arm64": [
                    {"name": "Typing_Extensions", "version": "4.0", "rank": 1, "status": "source"},
                    {"name": "sample", "version": "1.1", "rank": 2, "status": "missing"},
                    {"name": "bad<script>", "version": "<broken>", "rank": 3, "status": "missing"},
                    evil,
                ],
                "3.15 linux-x86_64": [],
                "3.14 pyodide": [evil],
                "3.15 linux-aarch64": [],
            },
        }
        self.coverage = self.root / "coverage.json"
        self.index = self.root / "most-wanted.json"
        patcher = mock.patch.dict(build_lab.TARGETS, LAB, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_build(self, config=None):
        self.coverage.write_text(json.dumps(self.scan), encoding="utf-8")
        self.index.write_text(json.dumps(self.wanted), encoding="utf-8")
        return build_platform_pages.build(self.coverage, self.index, self.site, config)

    def read(self, platform):
        return (self.site / "platforms" / platform / "index.html").read_text(encoding="utf-8")

    def test_pages_counts_links_empty_and_sitemap(self):
        self.assertEqual(self.run_build(), 4)
        root = (self.site / "platforms" / "index.html").read_text(encoding="utf-8")
        win = self.read("win-arm64")
        linux = self.read("linux-x86_64")
        sitemap = (self.site / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("Windows ARM64", root)
        self.assertIn("0 of the top 3 PyPI packages (0.0%) have a prebuilt wheel on Windows ARM64 for Python 3.15", win)
        self.assertIn("Most-wanted wheels for Python 3.15", win)
        self.assertIn('href="../../p/typing-extensions/"', win)
        self.assertIn('<span class="status s-source">from source</span>', win)
        self.assertIn('<span class="status s-missing">can&#x27;t install</span>', win)
        self.assertEqual(win.count('<table class="matrix">'), 1)
        self.assertNotIn("<ol>", win)
        self.assertIn('<p class="meta">From the wheelgap 0.13.0 scan of 2026-11-17.</p>', win)
        self.assertIn("None of the top packages", linux)
        self.assertIn("3 of the top 3", linux)
        self.assertIn("/tracker/platforms/win-arm64/", sitemap)
        self.assertEqual(sitemap.count("<loc>https://wheelgap.github.io/tracker/platforms/win-arm64/</loc>"), 1)
        self.assertIn("default-src", win)
        self.assertIn('<link rel="alternate" type="application/atom+xml" title="New win-arm64 wheels" href="../../new/win-arm64.xml">', win)

    def test_escaping(self):
        self.run_build()
        win = self.read("win-arm64")
        self.assertIn('href="../../p/evil/"', win)
        self.assertIn("&lt;b&gt;&amp;", win)
        self.assertNotIn("<b>&", win)
        self.assertNotIn("bad<script>", win)
        self.assertNotIn("<script", win)

    def test_social_cards_on_platform_index_and_details(self):
        self.run_build()
        paths = ["", "win-arm64/", "linux-x86_64/", "linux-aarch64/", "pyodide/"]
        for path in paths:
            with self.subTest(path=path):
                page = (self.site / "platforms" / path / "index.html").read_text(encoding="utf-8")
                title = re.search(r"<title>(.*?)</title>", page).group(1)
                description = re.search(r'<meta name="description" content="([^"]*)">', page).group(1)
                canonical = f"https://wheelgap.github.io/tracker/platforms/{path}"
                for name, value in {
                    "type": "website", "title": title, "description": description,
                    "url": canonical, "image": "https://wheelgap.github.io/tracker/og.png",
                    "image:width": "1280", "image:height": "640",
                }.items():
                    self.assertIn(f'<meta property="og:{name}" content="{value}">', page)
                self.assertIn(f'<link rel="canonical" href="{canonical}">', page)
                self.assertIn('<meta property="og:image:alt" content="wheelgap tracker:', page)
                self.assertIn('<meta name="twitter:card" content="summary_large_image">', page)

    def test_social_cards_escape_platform_names_and_urls(self):
        friendly = 'ARM "fast" <test> & small'
        base = 'https://example.test/"<test>&/'
        with mock.patch.dict(build_pages.PLATFORM_NAMES, {"win-arm64": friendly}), \
                mock.patch.object(build_platform_pages, "BASE", base):
            self.run_build()
        page = self.read("win-arm64")
        title = f"Python 3.15 packages without {friendly} wheels"
        description = f"0 of the top 3 PyPI packages (0.0%) have a prebuilt wheel on {friendly} for Python 3.15."
        self.assertIn(f'<meta property="og:title" content="{html.escape(title)}">', page)
        self.assertIn(f'<meta property="og:description" content="{html.escape(description)}">', page)
        url = html.escape(base + "platforms/win-arm64/")
        self.assertIn(f'<meta property="og:url" content="{url}">', page)
        self.assertIn(f'<link rel="canonical" href="{url}">', page)
        self.assertNotIn('<test>', page)

    def test_python_is_per_platform(self):
        # The newest Python (3.15) has no Pyodide target: the Pyodide page uses 3.14 and isn't empty.
        self.run_build()
        pyodide = self.read("pyodide")
        self.assertIn("for Python 3.14", pyodide)
        self.assertNotIn("3.15", pyodide)
        self.assertIn("2 of the top 3 PyPI packages (66.7%) have a prebuilt wheel or a Pyodide build", pyodide)
        self.assertIn('href="../../p/evil/"', pyodide)

    def test_campaign_links_match_platform_and_name_another_python(self):
        config = self.root / "campaigns.toml"
        config.write_text(
            '[[campaign]]\nid = "win-arm64"\ntitle = "Windows on ARM"\nplatform = "win-arm64"\ntop = 500\n'
            'start = 2026-11-01\npython = "3.14"\n\n'
            '[[campaign]]\nid = "linux"\ntitle = "Linux for the newest"\nplatform = "linux-x86_64"\ntop = 500\n'
            "start = 2026-11-01\n",
            encoding="utf-8",
        )
        self.run_build(config)
        win = self.read("win-arm64")
        linux = self.read("linux-x86_64")
        self.assertIn('<a href="../../campaigns/win-arm64/">Windows on ARM (Python 3.14)</a>', win)
        self.assertIn('<a href="../../campaigns/linux/">Linux for the newest</a>', linux)
        self.assertNotIn("campaigns/linux/", win)
        self.assertNotIn("Campaign:", self.read("pyodide"))

    def test_build_lab_link_uses_declared_target_labels(self):
        self.run_build()
        self.assertIn('href="../../#lab-section"', self.read("win-arm64"))
        self.assertNotIn("lab-section", self.read("linux-aarch64"))
        self.assertNotIn("lab-section", self.read("pyodide"))

    def test_index_lists_platforms_by_share_lowest_first(self):
        # Windows ARM64 0/3, Pyodide 2/3, Linux ARM64 3/3 and Linux x86_64 3/3 (tie, by name).
        self.run_build()
        root = (self.site / "platforms" / "index.html").read_text(encoding="utf-8")
        rows = re.findall(r'<tr><td><a href="([^"]+)/">([^<]+)</a></td><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td></tr>', root)
        self.assertEqual([r[0] for r in rows], ["win-arm64", "pyodide", "linux-aarch64", "linux-x86_64"])
        self.assertEqual(root.count('<table class="matrix">'), 1)
        self.assertNotIn("<ul>", root)
        description = re.search(r'<meta name="description" content="([^"]*)">', root).group(1)
        self.assertEqual(description, "Windows ARM64 has the fewest wheels: 0.0% of the top 3 on Python 3.15.")
        self.assertIn(f'<p class="lede">{description}</p>', root)
        by_platform = {r[0]: r for r in rows}
        self.assertEqual(by_platform["pyodide"][2:], ("3.14", "66.7% (wheel or Pyodide build)", "1"))
        self.assertEqual(by_platform["win-arm64"][2:], ("3.15", "0.0%", "3"))
        self.assertEqual(by_platform["linux-x86_64"][2:], ("3.15", "100.0%", "0"))

    def test_index_description_says_when_the_worst_share_counts_pyodide_builds(self):
        # With Windows ARM64 fully covered, Pyodide (2/3, one of them `bundled`) is the worst.
        for package in self.scan["packages"]:
            package["results"][0] = package["results"][3] = "wheel"
        self.run_build()
        root = (self.site / "platforms" / "index.html").read_text(encoding="utf-8")
        description = re.search(r'<meta name="description" content="([^"]*)">', root).group(1)
        self.assertEqual(
            description,
            "Pyodide (browser) has the fewest wheels: 66.7% of the top 3 on Python 3.14, counting Pyodide builds.",
        )

    def test_index_rows_match_each_platform_page(self):
        self.run_build()
        root = (self.site / "platforms" / "index.html").read_text(encoding="utf-8")
        rows = re.findall(r'<tr><td><a href="([^"]+)/">[^<]+</a></td><td>([^<]+)</td><td>([0-9.]+)%', root)
        for platform, python, percent in rows:
            with self.subTest(platform=platform):
                page = self.read(platform)
                self.assertIn(f"({percent}%) have", page)
                self.assertIn(f"for Python {python}.", page)

    def test_index_leaves_out_platforms_without_a_target(self):
        self.run_build()
        root = (self.site / "platforms" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("macos", root.lower().split("<main", 1)[1])
        self.assertEqual(root.count("<tr><td>"), 4)

    def test_rejects_stale_most_wanted_data(self):
        self.wanted["generated"] = "2026-11-16T03:00:00+00:00"
        with self.assertRaises(SystemExit):
            self.run_build()


class PackagePageRowLinkTests(unittest.TestCase):
    def test_matrix_row_headings_link_to_platform_pages(self):
        package = {
            "rank": 1,
            "name": "numpy",
            "version": "2.3.1",
            "downloads": 1,
            "pure": False,
            "error": None,
            "results": ["wheel", "source"],
        }
        scan = {
            "schema": 1,
            "generated": "2026-11-16T03:20:00+00:00",
            "wheelgap": "0.11.0",
            "summary": {},
            "targets": [
                {"label": "3.13 linux-x86_64", "python": "3.13", "platform": "linux-x86_64"},
                {"label": "3.13 musl-aarch64", "python": "3.13", "platform": "musl-aarch64"},
            ],
            "packages": [package],
        }
        page = build_pages.page(package, scan, "3.13")
        self.assertIn('<th scope="row"><a href="../../platforms/linux-x86_64/">Linux x86_64</a></th>', page)
        self.assertIn('href="../../platforms/musl-aarch64/"', page)


if __name__ == "__main__":
    unittest.main()
