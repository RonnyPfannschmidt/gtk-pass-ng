#!/usr/bin/env python3
"""Name the Fedora packages a build of this project will ask for.

`%pyproject_buildrequires` reports them only by failing a build and being asked
again, which is why rpmbuild-here.sh has a retry loop around it. That is fine
inside a build and useless when preparing the container the build runs in --
there is no build to fail yet. So the same declaration is read directly.

Every Fedora package that ships a Python distribution provides
``python3dist(name)``, so the requirements can be handed to dnf as they are
written, without a table mapping PyPI names to package names that would be
wrong the first time somebody added a dependency.

    python3 buildreqs-from-pyproject.py pyproject.toml
    python3dist(setuptools)
    python3dist(setuptools-scm)
    ...
"""

import re
import sys
import tomllib
from pathlib import Path


def requirement_name(requirement: str) -> str:
    """The distribution a requirement names, without the rest of it.

    Everything after the name is a version, an extra, or an environment
    marker, and none of them belong in a package name. The markers are not
    evaluated: this prepares a Linux container, and a requirement that only
    applies elsewhere resolves to a package Fedora has anyway.
    """
    return re.split(r"[<>=!~;\[ ]", requirement.strip(), maxsplit=1)[0]


def canonical(name: str) -> str:
    """The name as a Provides spells it: PEP 503 normalisation."""
    return re.sub(r"[-_.]+", "-", name).lower()


def build_requirements(pyproject: dict) -> list[str]:
    """What has to be installed before this project can be built.

    Both halves of it: what the build backend needs to run at all, and what the
    project declares for itself -- which the RPM build needs too, because
    building a wheel imports the package metadata.
    """
    declared = list(pyproject.get("build-system", {}).get("requires", []))
    declared += list(pyproject.get("project", {}).get("dependencies", []))

    seen = {}
    for requirement in declared:
        name = canonical(requirement_name(requirement))
        if name:
            seen[name] = None
    return [f"python3dist({name})" for name in seen]


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "pyproject.toml")
    with path.open("rb") as handle:
        pyproject = tomllib.load(handle)
    for capability in build_requirements(pyproject):
        print(capability)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
