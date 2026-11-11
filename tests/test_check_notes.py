"""Offline checks for scripts/check_notes.py (no network)."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from scripts import check_notes

LABELS = [
    {"label": "3.13 linux-x86_64", "platform": "linux-x86_64"},
    {"label": "3.13 musl-aarch64", "platform": "musl-aarch64"},
]


def coverage(targets=None):
    return {"targets": targets if targets is not None else LABELS}


def note_toml(
    platforms='["musl-aarch64"]',
    kind="alternative",
    text="Use the binary extra.",
    links='["https://example.com/docs"]',
    versions=None,
    updated="2026-11-11",
):
    extra = f'versions = "{versions}"\n' if versions is not None else ""
    return (
        f"[[note]]\n"
        f"platforms = {platforms}\n"
        f'kind = "{kind}"\n'
        f'text = "{text}"\n'
        f"links = {links}\n"
        f"{extra}"
        f"updated = {updated}\n"
    )


class CheckNotesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.notes = self.root / "notes"
        self.notes.mkdir()

    def write(self, name, body):
        path = self.notes / name
        path.write_text(body, encoding="utf-8")
        return path

    def problems(self, scan=None):
        return check_notes.problems(self.notes, scan if scan is not None else coverage())

    def test_valid_note_is_clean(self):
        self.write("psycopg2.toml", note_toml())
        self.assertEqual(self.problems(), [])

    def test_all_platforms_is_accepted(self):
        self.write("psycopg2.toml", note_toml(platforms='["all"]'))
        self.assertEqual(self.problems(), [])

    def test_readme_is_ignored(self):
        self.write("README.md", "not toml")
        self.assertEqual(self.problems(), [])

    def test_filename_must_be_normalized(self):
        self.write("Py_Crypto.toml", note_toml())
        found = self.problems()
        self.assertTrue(any("normalized" in p for p in found), found)

    def test_unreadable_toml_is_reported(self):
        self.write("broken.toml", "[[note]\n")
        found = self.problems()
        self.assertTrue(found and "broken.toml" in found[0], found)

    def test_missing_note_table_is_reported(self):
        self.write("empty.toml", "kind = \"alternative\"\n")
        found = self.problems()
        self.assertTrue(any("at least one" in p for p in found), found)

    def test_unknown_kind_is_reported(self):
        self.write("psycopg2.toml", note_toml(kind="tip"))
        found = self.problems()
        self.assertTrue(any("kind" in p for p in found), found)

    def test_unknown_platform_is_reported(self):
        self.write("psycopg2.toml", note_toml(platforms='["alpine"]'))
        found = self.problems()
        self.assertTrue(any("unknown platform" in p for p in found), found)

    def test_all_mixed_with_a_name_is_reported(self):
        self.write("psycopg2.toml", note_toml(platforms='["all", "musl-aarch64"]'))
        found = self.problems()
        self.assertTrue(any("unknown platform" in p or "all" in p for p in found), found)

    def test_empty_text_is_reported(self):
        self.write("psycopg2.toml", note_toml(text="   "))
        found = self.problems()
        self.assertTrue(any("text" in p for p in found), found)

    def test_text_over_500_characters_is_reported(self):
        self.write("psycopg2.toml", note_toml(text="x" * 501))
        found = self.problems()
        self.assertTrue(any("500" in p for p in found), found)

    def test_http_link_is_rejected(self):
        self.write("psycopg2.toml", note_toml(links='["http://example.com/docs"]'))
        found = self.problems()
        self.assertTrue(any("https" in p for p in found), found)

    def test_updated_must_be_a_date(self):
        self.write("psycopg2.toml", note_toml(updated='"2026-11-11"'))
        found = self.problems()
        self.assertTrue(any("updated must be a date" in p for p in found), found)

    def test_versions_if_present_must_be_a_string(self):
        self.write("psycopg2.toml", note_toml() + "versions = 3\n")
        found = self.problems()
        self.assertTrue(any("versions" in p for p in found), found)

    def test_optional_versions_string_is_accepted(self):
        self.write("psycopg2.toml", note_toml(versions="<3"))
        self.assertEqual(self.problems(), [])

    def test_real_notes_pass_against_coverage(self):
        repo = Path(__file__).resolve().parent.parent
        scan = json.loads((repo / "data" / "coverage.json").read_text(encoding="utf-8"))
        self.assertEqual(check_notes.problems(repo / "notes", scan), [])

    def test_cli_exits_zero_on_the_repo_notes(self):
        repo = Path(__file__).resolve().parent.parent
        self.assertEqual(
            check_notes.main([str(repo / "notes"), str(repo / "data" / "coverage.json")]),
            0,
        )

    def test_cli_exits_nonzero_when_a_note_is_bad(self):
        self.write("psycopg2.toml", note_toml(kind="tip"))
        coverage_path = self.root / "coverage.json"
        coverage_path.write_text(json.dumps(coverage()), encoding="utf-8")
        self.assertEqual(check_notes.main([str(self.notes), str(coverage_path)]), 1)

    def test_normalize_name(self):
        self.assertEqual(check_notes.normalize_name("Py_Crypto"), "py-crypto")
        self.assertEqual(check_notes.normalize_name("psycopg2"), "psycopg2")


# Keep a cheap check that the date type the checker wants is what tomllib emits.
class TomlDateTests(unittest.TestCase):
    def test_bare_toml_date_is_datetime_date(self):
        import tomllib

        data = tomllib.loads("updated = 2026-11-11\n")
        self.assertIsInstance(data["updated"], dt.date)
        self.assertNotIsInstance(data["updated"], dt.datetime)
