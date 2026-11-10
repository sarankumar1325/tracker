# wheelgap tracker

**Python wheel coverage for the top 5,000 PyPI packages**, across Linux x86_64 and ARM64, Alpine (musl), macOS, Windows x86_64 and ARM64 for Python 3.13, 3.14 and 3.15 and free-threaded 3.14t and 3.15t, plus Pyodide where it has a build (3.13 and 3.14).

**→ [wheelgap.github.io/tracker](https://wheelgap.github.io/tracker/)**

A package without a wheel for your platform is compiled from source on install (slow, and it needs a compiler), or can't be installed at all. This site shows where those gaps are, package by package.

## How it works

- Every night, [`.github/workflows/scan.yml`](.github/workflows/scan.yml) runs [wheelgap](https://github.com/wheelgap/wheelgap)'s scanner (`python -m wheelgap.scan`) over the top packages from [top-pypi-packages](https://hugovk.dev/top-pypi-packages/). It checks each package's latest release against every platform.
- The full result goes to [`data/coverage.json`](data/coverage.json). A one-line summary per day is appended to [`data/history.json`](data/history.json), so coverage over time is kept without storing every scan.
- The site in [`site/`](site/) is plain HTML, CSS and JavaScript, with no build step. It's published to GitHub Pages together with the data.

## Using the data

`data/coverage.json` (schema 1):

- `targets`: the list of `{label, python, platform}`. Each package's `results` lines up with it.
- `summary`: per target label, counts of `wheel`, `source` (sdist only, so it builds on install), `missing` (can't install) and `unknown`.
- `packages`: `rank`, `name`, `version` (the latest release), `downloads` (30 days), `pure` (has a wheel that works everywhere), `error` and `results`.

The data is CC0: use it for anything. The code is MIT.

## API for scripts and agents

To check one package, fetch its own small file (about 1.3 KB) instead of the whole scan:

```sh
curl -fsS https://wheelgap.github.io/tracker/data/packages/numpy.json
```

It has the package's `name`, `version`, `rank`, `pure` and `error`, the scan's `generated` time and `wheelgap` version, and `results`: the same values as `coverage.json`, keyed by target label, e.g. `"3.13 linux-aarch64": "wheel"`. Use the [normalized name](https://packaging.python.org/en/latest/specifications/name-normalization/) (lowercase, with runs of `-`, `_` and `.` replaced by `-`); a 404 means the package isn't in the scan's top 5,000, or the name isn't normalized. [`data/packages.json`](https://wheelgap.github.io/tracker/data/packages.json) lists every package with its version, and the targets, including the glibc, musl and macOS baselines each result assumes. Both carry `"schema": 1`, which goes up if a field changes meaning or is removed. The files are built from `coverage.json` when the site is published, by [`scripts/build_lookup.py`](scripts/build_lookup.py).

## Badges

Each package has a [shields.io endpoint](https://shields.io/badges/endpoint-badge) badge showing how many of the eight native platforms have a wheel for the newest Python in the scan, e.g. for numpy:

```markdown
[![wheels](https://img.shields.io/endpoint?url=https://wheelgap.github.io/tracker/badge/numpy.json)](https://wheelgap.github.io/tracker/#package=numpy)
```

Use the normalized name, as for the API; the package lookup on the site shows the snippet with a Copy button. Badges are built when the site is published, by [`scripts/build_badges.py`](scripts/build_badges.py), and only exist for packages in the top 5,000.

## Caveats

- Only the **latest release** of each package is checked. Your pinned version may differ, so for that, run `uvx wheelgap` on your lockfile.
- **Pyodide** counts wheels on PyPI only. Pyodide also ships its own builds of many popular packages; `wheelgap --pyodide-lock` knows about those.
- Linux wheels are judged against glibc 2.36 and musl 1.2, and macOS against 14.0, which are wheelgap's defaults.

## Contributing

The site is deliberately simple, so it's a good place to start. Ideas and fixes are welcome, as are reports of anything that looks wrong ([open an issue](https://github.com/wheelgap/tracker/issues)). The bigger plan is on the [roadmap](https://github.com/wheelgap/wheelgap/discussions/43).
