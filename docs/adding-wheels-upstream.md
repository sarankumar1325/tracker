# How to get a missing wheel added upstream

This is a short guide for someone who has found a missing wheel on the [tracker](https://wheelgap.github.io/tracker/) and wants to help the project ship one. It is the “how-to for adding wheels upstream” from [phase 3 of the roadmap](https://github.com/wheelgap/wheelgap/discussions/43).

The usual fix is a CI job, not a patch to the library itself. The notes below stay short on purpose: follow the project’s own contributing guide, and prefer links to current tooling docs over a copied config that will go stale.

## 1. Ask first

Search the project’s issues and discussions for the platform (musllinux, aarch64, Windows on ARM, free-threaded builds, and so on). If nobody has asked, open **one** issue that:

- links the [package page](https://wheelgap.github.io/tracker/p/numpy/) on this tracker (use the package’s normalized name);
- names the platforms that have no wheel;
- offers to do the work.

Respect a “not now”. Never file the same issue across many projects at once; a burst of drive-by tickets is worse than a missing wheel.

## 2. The usual fix: cibuildwheel

Most projects already ship wheels with [cibuildwheel](https://cibuildwheel.pypa.io/) in GitHub Actions. The [setup page](https://cibuildwheel.pypa.io/en/stable/setup/) and the [options reference](https://cibuildwheel.pypa.io/en/stable/options/) are the place to start. When you add a platform, cover:

- **musllinux** (Alpine and other musl systems). cibuildwheel builds these by default on Linux; see [Linux builds](https://cibuildwheel.pypa.io/en/stable/platforms/#linux). [pygit2#1266](https://github.com/libgit2/pygit2/pull/1266) is a compact example of turning that on and publishing the wheels.
- **Linux aarch64.** GitHub’s [arm64 hosted runners](https://docs.github.com/en/actions/using-github-hosted-runners/using-github-hosted-runners/about-github-hosted-runners#standard-github-hosted-runners-for-public-repositories) can build natively. QEMU still works, and is slower. [psutil#2425](https://github.com/giampaolo/psutil/pull/2425) added manylinux aarch64 wheels this way.
- **Windows on ARM.** cibuildwheel documents the [Windows ARM64](https://cibuildwheel.pypa.io/en/stable/platforms/#windows) target. [PyYAML#864](https://github.com/yaml/pyyaml/pull/864) is an example of adding `win_arm64` to an existing matrix.
- **Free-threaded builds** (`cp313t`, `cp314t`, …). Enable them with [`CIBW_ENABLE`](https://cibuildwheel.pypa.io/en/stable/options/#enable) (or `CIBW_ENABLE=cpython-freethreading` in recent versions). Only do this if the extension module is actually safe on the free-threaded ABI; the project may want a separate issue for that.
- **Testing the wheel** in CI with [`test-command`](https://cibuildwheel.pypa.io/en/stable/options/#test-command) (`CIBW_TEST_COMMAND`), so a broken wheel does not get uploaded.

Keep the change to the workflow and the project’s existing test suite. Don’t add a new backend or rewrite the package’s build unless the maintainers ask for that.

## 3. Pure-Python packages that only ship an sdist

If the package has no compiled code, a single `py3-none-any` wheel covers every platform at once. The usual `pyproject.toml` is:

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"
```

Then, from a clean checkout:

```sh
python -m pip install build
python -m build
# dist/ will contain both the sdist and a py3-none-any wheel
```

[Packaging Python Projects](https://packaging.python.org/en/latest/tutorials/packaging-projects/) walks through the same steps, including trusted publishing to PyPI. A project that already uses setuptools but never runs `python -m build` in CI often only needs that job, not a new backend.

## 4. How to check it worked

Against the new release, once it is on PyPI:

```sh
uvx wheelgap <name>==<new version> -t all
```

That should show a wheel (or a `py3-none-any` wheel) on the platforms you added. This tracker’s nightly scan will pick the new version up the next night; the package page and the most-wanted lists update when that scan is published.

If `wheelgap` still reports `source` or `missing` for a platform you think you built, look at the wheel tags (`auditwheel` / `wheel tags`) and at wheelgap’s glibc, musl and macOS baselines, which are listed in [the tracker caveats](https://github.com/wheelgap/tracker#caveats).
