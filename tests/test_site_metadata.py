"""The hand-written pages' metadata for search engines and social cards (#164)."""

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://wheelgap.github.io/tracker/"
PAGES = {"site/index.html": BASE, "site/check/index.html": f"{BASE}check/"}


class Head(HTMLParser):
    """Collects the <meta property>, <link rel="canonical"> and JSON-LD blocks of a page."""

    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.canonical: list[str] = []
        self.json_ld: list[str] = []
        self._in_ld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and "property" in a:
            self.meta[a["property"]] = a.get("content", "")
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical.append(a.get("href", ""))
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = True
            self.json_ld.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_ld = False

    def handle_data(self, data):
        if self._in_ld:
            self.json_ld[-1] += data


def head(path: str) -> Head:
    parser = Head()
    parser.feed((ROOT / path).read_text(encoding="utf-8"))
    return parser


def published_data_files() -> set[str]:
    """The files the publish step ("Assemble the site" in scan.yml) puts in _site/data/: the
    committed data/*.json it copies, and every _site/data/<file> it names."""
    workflow = (ROOT / ".github" / "workflows" / "scan.yml").read_text(encoding="utf-8")
    step = workflow.split("- name: Assemble the site", 1)[1].split("\n      - ", 1)[0]
    files = set(re.findall(r"_site/data/([\w.-]+\.\w+)\b", step))
    if "cp data/*.json _site/data/" in step:
        files |= {p.name for p in (ROOT / "data").glob("*.json")}
    return files


class SiteMetadataTests(unittest.TestCase):
    def test_home_page_has_a_dataset_block(self):
        blocks = head("site/index.html").json_ld
        self.assertEqual(len(blocks), 1)
        data = json.loads(blocks[0])
        self.assertEqual(data["@context"], "https://schema.org")
        self.assertEqual(data["@type"], "Dataset")
        self.assertEqual(data["url"], BASE)
        self.assertEqual(data["license"], "https://creativecommons.org/publicdomain/zero/1.0/")
        self.assertIs(data["isAccessibleForFree"], True)
        self.assertEqual(data["creator"], {"@type": "Organization", "name": "wheelgap", "url": "https://github.com/wheelgap"})
        self.assertNotIn("dateModified", data)  # a static page would go stale
        formats = {d["contentUrl"]: d["encodingFormat"] for d in data["distribution"]}
        self.assertEqual(formats, {
            f"{BASE}data/coverage.json": "application/json",
            f"{BASE}data/coverage.csv": "text/csv",
            f"{BASE}data/history.csv": "text/csv",
        })
        self.assertTrue(all(d["@type"] == "DataDownload" for d in data["distribution"]))

    def test_description_matches_the_meta_description(self):
        page = (ROOT / "site/index.html").read_text(encoding="utf-8")
        meta = re.search(r'<meta name="description" content="([^"]*)">', page).group(1)
        self.assertEqual(json.loads(head("site/index.html").json_ld[0])["description"], meta)

    def test_every_distribution_is_a_file_the_publish_step_writes(self):
        files = published_data_files()
        self.assertIn("coverage.csv", files)  # the workflow parse itself works
        for d in json.loads(head("site/index.html").json_ld[0])["distribution"]:
            url = d["contentUrl"]
            with self.subTest(url=url):
                self.assertTrue(url.startswith(f"{BASE}data/"), url)
                self.assertIn(url.removeprefix(f"{BASE}data/"), files)

    def test_canonical_link_and_social_image_tags(self):
        for path, url in PAGES.items():
            with self.subTest(path=path):
                page = head(path)
                self.assertEqual(page.canonical, [url])
                self.assertEqual(page.meta.get("og:url"), url)
                self.assertEqual(page.meta.get("og:image:width"), "1280")
                self.assertEqual(page.meta.get("og:image:height"), "640")
                self.assertTrue(page.meta.get("og:image:alt"))


if __name__ == "__main__":
    unittest.main()
