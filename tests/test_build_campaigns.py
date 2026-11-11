"""Offline checks for the musllinux aarch64 campaign page."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import build_campaigns, build_pages


CONFIG = """
[[campaign]]
id = "musl-aarch64"
title = "musllinux aarch64 wheels for the top 500"
platform = "musl-aarch64"
top = 2
start = "2026-11-10"
how_to = "https://github.com/wheelgap/tracker/blob/main/docs/adding-wheels-upstream.md"
"""


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.coverage = self.root / "coverage.json"
        self.history = self.root / "history.json"
        self.changes = self.root / "changes.json"
        self.config = self.root / "campaigns.toml"
        self.site = self.root / "_site"
        self.config.write_text(CONFIG, encoding="utf-8")
        self.scan = {
            "schema": 1,
            "generated": "2026-11-11T00:00:00+00:00",
            "wheelgap": "0.8.0",
            "targets": [
                {"label": "3.13 linux-x86_64", "python": "3.13", "platform": "linux-x86_64"},
                {"label": "3.13 musl-aarch64", "python": "3.13", "platform": "musl-aarch64"},
                {"label": "3.14t musl-aarch64", "python": "3.14t", "platform": "musl-aarch64"},
                {"label": "3.15 musl-aarch64", "python": "3.15", "platform": "musl-aarch64"},
            ],
            "packages": [
                {"rank": 1, "name": "NumPy", "version": "2.0", "error": None,
                 "results": ["wheel", "source", "source", "wheel"]},
                {"rank": 2, "name": "psycopg2", "version": "2.9", "error": None,
                 "results": ["wheel", "source", "source", "source"]},
                {"rank": 3, "name": "outside-top", "version": "1.0", "error": None,
                 "results": ["wheel", "missing", "missing", "missing"]},
                {"rank": 4, "name": "failed", "version": None, "error": "lookup failed",
                 "results": ["unknown", "unknown", "unknown", "unknown"]},
            ],
        }
        self.history_data = [
            {"date": "2026-11-09", "wheelgap": "0.8.0", "packages": 100,
             "summary": {"3.15 musl-aarch64": {"wheel": 80, "source": 15, "missing": 5, "unknown": 0}}},
            {"date": "2026-11-11", "wheelgap": "0.8.0", "packages": 100,
             "summary": {"3.15 musl-aarch64": {"wheel": 85, "source": 10, "missing": 5, "unknown": 0}}},
        ]
        self.changes_data = [
            {"date": "2026-11-09", "gained": [
                {"name": "NumPy", "version": "1.9", "target": "3.15 musl-aarch64", "from": "source", "to": "wheel"},
            ], "lost": []},
            {"date": "2026-11-11", "gained": [
                {"name": "NumPy", "version": "2.0", "target": "3.15 musl-aarch64", "from": "source", "to": "wheel"},
                {"name": "outside-top", "version": "1.0", "target": "3.15 musl-aarch64", "from": "missing", "to": "wheel"},
                {"name": "psycopg2", "version": "2.9", "target": "3.15 linux-x86_64", "from": "source", "to": "wheel"},
            ], "lost": []},
        ]

    def write_inputs(self):
        self.coverage.write_text(json.dumps(self.scan), encoding="utf-8")
        self.history.write_text(json.dumps(self.history_data), encoding="utf-8")
        self.changes.write_text(json.dumps(self.changes_data), encoding="utf-8")

    def built_page(self) -> str:
        self.write_inputs()
        self.assertEqual(
            build_campaigns.build(self.coverage, self.history, self.changes, self.config, self.site),
            1,
        )
        return (self.site / "campaigns" / "musl-aarch64" / "index.html").read_text(encoding="utf-8")

    def test_uses_newest_non_free_threaded_python_and_top_n(self):
        page = self.built_page()
        # 3.15, not 3.14t or 3.13: NumPy has a wheel, psycopg2 does not, so 1 of 2.
        self.assertIn("Python 3.15", page)
        self.assertNotIn("3.14t", page)
        self.assertIn("<strong>50%</strong>", page)
        self.assertIn("1 of 2", page)
        self.assertIn("psycopg2", page)
        self.assertIn("from source", page)
        self.assertNotIn("outside-top", page)
        self.assertNotIn("failed", page)
        self.assertIn('href="../../p/numpy/"', page)
        self.assertIn('href="https://pypi.org/project/psycopg2/"', page)
        self.assertNotIn("Source</th>", page)

    def test_trend_uses_history_for_the_badge_python_label(self):
        page = self.built_page()
        self.assertIn("2026-11-09", page)
        self.assertIn("80 / 100", page)
        self.assertIn("85 / 100", page)
        self.assertIn("nightly scan", page.lower())

    def test_done_is_gains_on_or_after_start_in_the_current_top_n(self):
        page = self.built_page()
        # 11 Nov gain for NumPy is in; 9 Nov is before start; outside-top is rank 3; linux-x86_64 is wrong target.
        done = page.split(">Done</h2>", 1)[1]
        self.assertIn("NumPy", done)
        self.assertIn("2026-11-11", done)
        self.assertNotIn("2026-11-09", done)
        self.assertNotIn("outside-top", done)
        self.assertNotIn("psycopg2", done)

    def test_ask_upstream_and_how_to_link_and_no_javascript(self):
        page = self.built_page()
        self.assertIn("Ask upstream first", page)
        self.assertIn("https://github.com/wheelgap/tracker/blob/main/docs/adding-wheels-upstream.md", page)
        self.assertNotIn("<script", page)
        self.assertIn('href="../../style.css"', page)

    def test_appends_campaign_url_to_existing_sitemap(self):
        self.write_inputs()
        build_pages.build(self.coverage, self.site)
        build_campaigns.build(self.coverage, self.history, self.changes, self.config, self.site)
        sitemap = (self.site / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("https://wheelgap.github.io/tracker/</loc>", sitemap)
        self.assertIn("https://wheelgap.github.io/tracker/p/numpy/</loc>", sitemap)
        self.assertIn("https://wheelgap.github.io/tracker/campaigns/musl-aarch64/</loc>", sitemap)

    def test_cli_writes_the_page(self):
        self.write_inputs()
        result = subprocess.run(
            [sys.executable, str(Path(build_campaigns.__file__)),
             str(self.coverage), str(self.history), str(self.changes),
             str(self.config), str(self.site)],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("1 pages", result.stdout)
        self.assertTrue((self.site / "campaigns" / "musl-aarch64" / "index.html").exists())

    def test_rejects_unknown_scan_schema(self):
        self.scan["schema"] = 2
        self.write_inputs()
        with self.assertRaisesRegex(SystemExit, "schema 2.*expected 1"):
            build_campaigns.build(self.coverage, self.history, self.changes, self.config, self.site)
        self.assertFalse((self.site / "campaigns").exists())


if __name__ == "__main__":
    unittest.main()
