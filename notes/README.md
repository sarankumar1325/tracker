# Package notes

Notes record what the nightly scan cannot: a binary extra to install, a system library to add first, a conda-forge build, or an upstream issue to follow. The scan still says *that* a wheel is missing; a note says *what to do about it*.

This is v0 of the format, proposed in [#27](https://github.com/wheelgap/tracker/issues/27). The earlier discussion in [wheelgap#109](https://github.com/wheelgap/wheelgap/discussions/109) stays open if the fields need to change. Notes are not shown on the site yet; that is the next step ([#28](https://github.com/wheelgap/tracker/issues/28)).

## Files

One TOML file per package, named for the [normalized package name](https://packaging.python.org/en/latest/specifications/name-normalization/) (lowercase, with runs of `-`, `_` and `.` replaced by a single `-`): `notes/psycopg2.toml`, `notes/mysqlclient.toml`.

Each file has one or more `[[note]]` tables:

```toml
[[note]]
platforms = ["musl-aarch64", "musl-x86_64"]  # wheelgap target names, or ["all"]
kind = "alternative"         # workaround | alternative | upstream-issue | other-source
text = "psycopg2 has no musllinux wheels. psycopg2-binary does: `pip install psycopg2-binary`."
links = ["https://www.psycopg.org/docs/install.html"]
versions = "<3"              # optional: shown only while the latest release matches
updated = 2026-11-11
```

## Fields

- **platforms**: a list of wheelgap target names, taken from the `platform` field in `data/coverage.json`'s `targets` (`linux-x86_64`, `linux-aarch64`, `musl-x86_64`, `musl-aarch64`, `macos-x86_64`, `macos-arm64`, `win-amd64`, `win-arm64`, `pyodide`). Use `["all"]` when the note applies to every target. Do not mix `"all"` with named platforms.
- **kind**: one of `workaround` (install a system library, set a flag), `alternative` (a different package or extra that has the wheel), `upstream-issue` (a ticket to follow), or `other-source` (conda-forge, a distro package, …).
- **text**: one or two sentences, non-empty, at most 500 characters. Write what someone should *do*.
- **links**: one or more `https://` URLs that back the claim: upstream docs, the issue, or a feedstock. Check what you claim.
- **versions** (optional): a string describing which releases the note applies to, for example `"<3"`. A note should stop being shown once this no longer matches the latest release (that filtering lands with #28).
- **updated**: a TOML date (`YYYY-MM-DD`), the day the note was last checked.

A note is also meant to retire itself once the scan shows a wheel on every platform it lists. That hiding, and showing notes on package pages, is [#28](https://github.com/wheelgap/tracker/issues/28).

## Checking

From the repository root, standard library only:

```sh
python3 scripts/check_notes.py
```

The [Check](../.github/workflows/check.yml) workflow runs this on every pull request, and `tests/test_check_notes.py` covers the error cases. Please run the checker before you send a notes change.

To add a note, open a pull request with the new `notes/<name>.toml`. Pick packages that are not already covered, and keep the claim checkable from the links you give.
