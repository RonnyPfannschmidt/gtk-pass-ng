"""Deriving the build container's package list from pyproject.toml.

The container the RPM is built in has the project's build requirements in it
already, so that a build installs nothing. They are read from the one place
that declares them rather than typed out a second time, because a second list
is a list that goes stale -- quietly, and only as a slower build, which is the
kind of wrong nobody notices.
"""

import importlib.util
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "packaging" / "buildreqs-from-pyproject.py"


def load():
    """Import the script, which is not part of the installed package."""
    spec = importlib.util.spec_from_file_location("buildreqs", SCRIPT)
    assert spec is not None and spec.loader is not None, f"cannot import {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


buildreqs = load()


class TestNamingARequirement:
    @pytest.mark.parametrize(
        "requirement,expected",
        [
            ("setuptools", "setuptools"),
            ("setuptools>=77", "setuptools"),
            ("PyGObject>=3.42.0", "PyGObject"),
            ("secretstorage>=3.3.0; sys_platform == 'linux'", "secretstorage"),
            ("requests[socks]>=2", "requests"),
            ("  spaced >= 1 ", "spaced"),
            ("pinned==1.0", "pinned"),
            ("compatible~=1.0", "compatible"),
            ("excluded!=1.0", "excluded"),
        ],
    )
    def test_the_name_is_taken_and_the_rest_left(self, requirement, expected):
        assert buildreqs.requirement_name(requirement) == expected


class TestCanonicalNames:
    """A Provides spells the name the way PEP 503 does, not the way a
    dependency happens to be written.
    """

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("PyGObject", "pygobject"),
            ("setuptools_scm", "setuptools-scm"),
            ("python.gnupg", "python-gnupg"),
            ("Already-Fine", "already-fine"),
        ],
    )
    def test_it_is_normalised(self, name, expected):
        assert buildreqs.canonical(name) == expected


class TestWhatIsAskedFor:
    def test_both_halves_are_included(self):
        """The backend's own requirements, and the project's."""
        derived = buildreqs.build_requirements(
            {
                "build-system": {"requires": ["setuptools>=77"]},
                "project": {"dependencies": ["PyGObject>=3.42"]},
            }
        )

        assert derived == ["python3dist(setuptools)", "python3dist(pygobject)"]

    def test_a_name_asked_for_twice_is_named_once(self):
        derived = buildreqs.build_requirements(
            {
                "build-system": {"requires": ["setuptools>=77"]},
                "project": {"dependencies": ["setuptools"]},
            }
        )

        assert derived == ["python3dist(setuptools)"]

    def test_a_project_with_nothing_declared_asks_for_nothing(self):
        assert buildreqs.build_requirements({}) == []

    def test_this_project_resolves_to_what_it_declares(self):
        """Against the real file, so a dependency added here is covered.

        This is the check that matters: the container's package list is this
        function's output, so anything pyproject.toml gains has to appear in it
        without anybody remembering to edit a Containerfile.
        """
        with (ROOT / "pyproject.toml").open("rb") as handle:
            pyproject = tomllib.load(handle)

        derived = buildreqs.build_requirements(pyproject)

        declared = (
            pyproject["build-system"]["requires"]
            + (pyproject["project"]["dependencies"])
        )
        assert len(derived) == len(
            {buildreqs.canonical(buildreqs.requirement_name(r)) for r in declared}
        )
        assert "python3dist(pygobject)" in derived
        assert "python3dist(python-gnupg)" in derived
