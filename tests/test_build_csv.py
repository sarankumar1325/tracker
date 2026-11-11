"""Offline checks for the coverage.csv export."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_csv


class BuildCsvTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.coverage = self.root / "coverage.json"
        self.out = self.root / "coverage.csv"
        self.scan = {
            "schema": 1,
            "generated": "2026-11-11T00:00:00+00:00",
            "targets": [{"label": "3.13 linux-x86_64"}, {"label": "3.14t musl-aarch64"}],
            "packages": [
                {
                    "rank": 1,
                    "name": "boto3",
                    "version": "1.2.3",
                    "downloads": 10,
                    "pure": True,
                    "error": None,
                    "results": ["wheel", "source"],
                },
                {
                    "rank": 2,
                    "name": "odd,name",
                    "version": None,
                    "downloads": 0,
                    "pure": False,
                    "error": 'lookup failed, "retry"',
                    "results": ["unknown", "n/a"],
                },
            ],
        }

    def write_scan(self):
        self.coverage.write_text(json.dumps(self.scan), encoding="utf-8")

    def test_writes_a_row_per_package_and_quotes_awkward_fields(self):
        self.write_scan()
        self.assertEqual(build_csv.build(self.coverage, self.out), 2)
        with self.out.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(
            rows[0],
            ["rank", "name", "version", "downloads", "pure", "error", "3.13 linux-x86_64", "3.14t musl-aarch64"],
        )
        self.assertEqual(rows[1], ["1", "boto3", "1.2.3", "10", "true", "", "wheel", "source"])
        self.assertEqual(rows[2], ["2", "odd,name", "", "0", "false", 'lookup failed, "retry"', "unknown", "n/a"])
        # The comma in the name and error is quoted, so a spreadsheet keeps one field.
        text = self.out.read_text(encoding="utf-8")
        self.assertIn('"odd,name"', text)
        self.assertIn('"lookup failed, ""retry"""', text)

    def test_rejects_an_unexpected_schema(self):
        self.scan["schema"] = 2
        self.write_scan()
        with self.assertRaises(SystemExit) as caught:
            build_csv.build(self.coverage, self.out)
        self.assertIn("schema 2", str(caught.exception))
