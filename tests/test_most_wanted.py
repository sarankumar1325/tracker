"""Offline checks for the per-target most-wanted data export."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import build_most_wanted


class MostWantedTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.coverage = self.root / "coverage.json"
        self.out = self.root / "data" / "most-wanted.json"
        self.scan = {
            "schema": 1,
            "generated": "2026-11-11T00:00:00+00:00",
            "targets": [{"label": "3.13 linux-x86_64"}, {"label": "3.14t musl-aarch64"}],
            "packages": [
                {"rank": 8, "name": "later", "version": "1.0", "error": None, "results": ["source", "wheel"]},
                {"rank": 1, "name": "failed", "version": None, "error": "lookup failed", "results": ["source", "missing"]},
                {"rank": 3, "name": "earlier", "version": "2.0", "error": None, "results": ["missing", "source"]},
                {"rank": 2, "name": "unknown", "version": "3", "error": None, "results": ["unknown", "n/a"]},
                {"rank": 4, "name": "bundled", "version": "4", "error": None, "results": ["bundled", "wheel"]},
            ],
        }

    def write_scan(self):
        self.coverage.write_text(json.dumps(self.scan), encoding="utf-8")

    def test_filters_and_orders_each_target(self):
        self.write_scan()
        self.assertEqual(build_most_wanted.build(self.coverage, self.out), 3)
        report = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(report, {
            "generated": self.scan["generated"],
            "targets": {
                "3.13 linux-x86_64": [
                    {"rank": 3, "name": "earlier", "version": "2.0", "status": "missing"},
                    {"rank": 8, "name": "later", "version": "1.0", "status": "source"},
                ],
                "3.14t musl-aarch64": [
                    {"rank": 3, "name": "earlier", "version": "2.0", "status": "source"},
                ],
            },
        })

    def test_caps_each_target_independently_at_fifty(self):
        self.scan["packages"] = [
            {"rank": n, "name": f"package-{n}", "version": "1", "error": None,
             "results": ["source", "missing" if n % 2 else "wheel"]}
            for n in range(120, 0, -1)
        ]
        self.write_scan()
        build_most_wanted.build(self.coverage, self.out)
        targets = json.loads(self.out.read_text(encoding="utf-8"))["targets"]
        self.assertEqual([p["rank"] for p in targets["3.13 linux-x86_64"]], list(range(1, 51)))
        self.assertEqual([p["rank"] for p in targets["3.14t musl-aarch64"]], list(range(1, 100, 2)))

    def test_cli_keeps_targets_with_no_gaps(self):
        self.scan["packages"] = []
        self.write_scan()
        result = subprocess.run(
            [sys.executable, str(Path(build_most_wanted.__file__)), str(self.coverage), str(self.out)],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("0 gaps", result.stdout)
        self.assertEqual(json.loads(self.out.read_text(encoding="utf-8"))["targets"], {
            "3.13 linux-x86_64": [], "3.14t musl-aarch64": [],
        })

    def test_rejects_unknown_scan_schema(self):
        self.scan["schema"] = 2
        self.write_scan()
        with self.assertRaisesRegex(SystemExit, "schema 2.*expected 1"):
            build_most_wanted.build(self.coverage, self.out)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
