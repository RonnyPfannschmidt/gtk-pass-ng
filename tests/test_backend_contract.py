"""Conformance suite every backend must satisfy.

A backend is done when this passes against it.  The suite is driven by the
declared entry points rather than by an import list, so a backend that is
registered but broken cannot hide.
"""

import importlib.metadata
import inspect
import subprocess
import sys
import textwrap

import pytest

from gtkpass.backends import (
    BackendMetadata,
    PasswordBackend,
    PasswordMetadata,
)

ENTRY_POINT_GROUP = "gtkpass.backends"
ENTRY_POINTS = sorted(
    importlib.metadata.entry_points(group=ENTRY_POINT_GROUP),
    key=lambda ep: ep.name,
)
ENTRY_POINT_NAMES = [ep.name for ep in ENTRY_POINTS]

#: Methods a concrete backend has to provide, with the signature the caller
#: is entitled to rely on.
ABSTRACT_METHODS = sorted(PasswordBackend.__abstractmethods__)


#: ``is_available()`` runs on the UI thread during window construction, so a
#: probe that blocks freezes the application at startup.  Generous enough that
#: a slow-but-working D-Bus round trip still passes.
AVAILABILITY_DEADLINE_SECONDS = 15


def load(name):
    """Load a backend class by entry point name."""
    (entry_point,) = (ep for ep in ENTRY_POINTS if ep.name == name)
    return entry_point.load()


def probe_availability(name):
    """Call ``is_available()`` out of process so a hang cannot wedge the suite.

    Returns the repr of the result, or raises if the probe did not finish.
    """
    script = textwrap.dedent(f"""
        import importlib.metadata as md
        (ep,) = (e for e in md.entry_points(group={ENTRY_POINT_GROUP!r})
                 if e.name == {name!r})
        print(repr(ep.load().is_available()))
    """)
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=AVAILABILITY_DEADLINE_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"{name}.is_available() did not return within "
            f"{AVAILABILITY_DEADLINE_SECONDS}s. It is called on the UI thread "
            f"during window construction, so this hangs the application at "
            f"startup whenever the service it probes is absent."
        )
    if result.returncode != 0:
        pytest.fail(f"{name}.is_available() raised:\n{result.stderr}")
    return result.stdout.strip()


def test_entry_points_are_declared():
    """The four shipped backends must be discoverable."""
    assert ENTRY_POINT_NAMES == ["demo", "direct", "pass", "secretservice"]


@pytest.mark.parametrize("name", ENTRY_POINT_NAMES)
class TestBackendClass:
    """Checks that need only the class, not a live instance."""

    def test_loads(self, name):
        assert load(name) is not None

    def test_is_a_password_backend(self, name):
        assert issubclass(load(name), PasswordBackend)

    def test_is_concrete(self, name):
        """No unimplemented abstract methods.

        A backend with a leftover abstract method cannot be instantiated at
        all; ``create()`` raises TypeError, which the window swallows into a
        generic 'failed to load' message.
        """
        missing = sorted(load(name).__abstractmethods__)
        assert missing == [], f"{name} does not implement: {missing}"

    def test_declares_metadata(self, name):
        cls = load(name)
        assert isinstance(cls.metadata, BackendMetadata)
        assert cls.metadata.id == name
        assert cls.metadata.name
        assert cls.metadata.icon

    def test_is_available_answers_promptly(self, name):
        """Availability probing must answer, quickly, without raising.

        It gates the UI and runs on the main thread.
        """
        assert probe_availability(name) in {"True", "False"}

    @pytest.mark.parametrize("method_name", ABSTRACT_METHODS)
    def test_signature_matches_the_interface(self, name, method_name):
        """Implementations must be callable the way the ABC promises."""
        cls = load(name)
        expected = inspect.signature(getattr(PasswordBackend, method_name))
        actual = inspect.signature(getattr(cls, method_name))
        assert list(actual.parameters) == list(expected.parameters)


class TestDemoBackendBehaviour:
    """The demo backend is always available, so it can be exercised directly."""

    @pytest.fixture
    def backend(self):
        return load("demo").create()

    def test_lists_password_metadata(self, backend):
        entries = backend.list_passwords()
        assert entries
        assert all(isinstance(entry, PasswordMetadata) for entry in entries)

    def test_get_password_returns_content(self, backend):
        first = backend.list_passwords()[0]
        entry = backend.get_password(first.name)
        assert entry.name == first.name
        assert entry.password

    def test_search_matches_by_name(self, backend):
        target = backend.list_passwords()[0].name
        assert target in [found.name for found in backend.search(target)]

    def test_search_for_nonsense_is_empty(self, backend):
        assert backend.search("zzz-no-such-entry-zzz") == []
