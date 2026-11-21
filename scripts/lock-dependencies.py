#!/usr/bin/env python3
"""Pin the dependency closure of an already tested Linux Python 3.12 environment.

Run with that environment's Python, then validate a fresh install and the full suite.
This deliberately excludes unrelated packages, editable paths and private index URLs.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections import deque
from importlib.metadata import distribution
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
HEADER = "# Linux CPython 3.12; generated from the tested environment by scripts/lock-dependencies.py.\n# Exact dependency versions; image/OS artifacts are verified separately.\n"


def closure(requirements):
    pending = deque(requirements)
    seen, versions = {}, {}
    environment = default_environment()
    while pending:
        req = Requirement(pending.popleft())
        key = canonicalize_name(req.name)
        extras = {"", *req.extras}
        previous = seen.setdefault(key, set())
        dist = distribution(req.name)
        if not req.specifier.contains(dist.version, prereleases=True):
            raise RuntimeError(f"Installed {key}=={dist.version} violates {req}")
        if extras <= previous:
            continue
        previous.update(extras)
        versions[key] = dist.version
        for text in dist.requires or []:
            child = Requirement(text)
            if child.marker is None or any(
                child.marker.evaluate({**environment, "extra": extra}) for extra in previous
            ):
                pending.append(str(child))
    return versions


def render(versions):
    return "".join(f"{name}=={versions[name]}\n" for name in sorted(versions))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux" or sys.version_info[:2] != (3, 12):
        parser.error("Generate/verify server locks in Linux CPython 3.12")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    runtime = closure(project["project"]["dependencies"])
    build = closure(project["build-system"]["requires"])
    dev = closure(project["project"]["optional-dependencies"]["dev"])
    contents = {
        "requirements-runtime.lock": HEADER + render(runtime),
        "requirements-build.lock": HEADER + render(build),
        "requirements-dev.lock": HEADER
        + "-r requirements-runtime.lock\n"
        + render({k: v for k, v in dev.items() if k not in runtime}),
    }
    for name, content in contents.items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise RuntimeError(f"{name} differs from this environment")
        else:
            path.write_text(content)
    print(
        f"{'Verified' if args.check else 'Pinned'} {len(runtime)} runtime packages, {len(build)} build packages, {len(dev)} dev packages"
    )


if __name__ == "__main__":
    main()
