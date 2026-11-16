"""Package pages carry schema.org structured data for search engines (#100)."""

import json
import re

from scripts import build_pages

TARGETS = [
    {"label": "3.13 linux-x86_64", "python": "3.13", "platform": "linux-x86_64"},
    {"label": "3.13 musl-aarch64", "python": "3.13", "platform": "musl-aarch64"},
]


def scan(name="numpy", version="2.3.1"):
    package = {"rank": 1, "name": name, "version": version, "downloads": 1, "pure": False, "error": None,
               "results": ["wheel", "source"]}
    return {"schema": 1, "generated": "2026-11-16T03:20:00+00:00", "wheelgap": "0.11.0", "targets": TARGETS,
            "summary": {}, "packages": [package]}


def blocks(page):
    return re.findall(r'<script type="application/ld\+json">\n(.*?)\n  </script>', page, re.S)


def build(data):
    return build_pages.page(data["packages"][0], data, "3.13")


def test_fields_and_valid_json():
    page = build(scan())
    (block,) = blocks(page)
    data = json.loads(block)
    assert data == {
        "@context": "https://schema.org",
        "@type": "SoftwareSourceCode",
        "name": "numpy",
        "url": "https://wheelgap.github.io/tracker/p/numpy/",
        "sameAs": "https://pypi.org/project/numpy/",
        "programmingLanguage": "Python",
        "description": data["description"],
        "version": "2.3.1",
    }
    # The same sentence as the meta description.
    meta = re.search(r'<meta name="description" content="([^"]*)">', page).group(1)
    assert meta == data["description"].replace("&", "&amp;")
    assert "numpy 2.3.1 has a prebuilt wheel for 1 of 2 platforms" in data["description"]


def test_a_script_end_tag_in_the_name_cannot_end_the_block():
    name = "evil</script><script>alert(1)</script>&x"
    page = build(scan(name=name))
    assert "</script><script>alert" not in page
    assert page.count("</script>") == 1  # only the block's own end tag
    (block,) = blocks(page)
    assert "<" not in block and ">" not in block and "&" not in block
    data = json.loads(block)
    assert data["name"] == name
    assert data["sameAs"] == f"https://pypi.org/project/{build_pages.canonical(name)}/"


def test_same_as_uses_the_canonical_name_like_url():
    data = json.loads(blocks(build(scan(name="Foo_Bar.baz")))[0])
    assert data["url"] == "https://wheelgap.github.io/tracker/p/foo-bar-baz/"
    assert data["sameAs"] == "https://pypi.org/project/foo-bar-baz/"


def test_no_version_leaves_the_key_out():
    page = build(scan(version=None))
    assert "version" not in json.loads(blocks(page)[0])


def test_unicode_stays_readable_and_parses():
    text = build_pages.json_ld("café", "1.0", "https://example.com/", "Ünïcode — fine")
    assert "café" in text  # not \\u-escaped beyond < > &
    (block,) = blocks(text)
    data = json.loads(block)
    assert data["name"] == "café" and data["description"] == "Ünïcode — fine"


def test_page_has_no_executable_script():
    # The JSON-LD block is data, not script: every <script> tag on the page is one.
    page = build(scan())
    tags = re.findall(r"<script\b[^>]*>", page, re.I)
    assert tags
    assert len(tags) == page.lower().count("<script")
    assert all(tag == '<script type="application/ld+json">' for tag in tags)
