"""Running out of a frozen bundle, which is what the Windows build ships.

There is no launcher script on Windows either, so the same rule applies as
everywhere else: whatever the application needs arranged, it arranges itself.
A PyInstaller bundle carries its own GTK, its own icon theme and its own
compiled schema, and none of that is on a path GLib would look at.

These run on Linux like everything else -- ``sys.frozen`` and ``sys._MEIPASS``
are what PyInstaller sets, and setting them is all it takes to ask what the
application would do inside a bundle.
"""

import os
from pathlib import Path

import pytest

from gtkpass import frozen, safety


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A directory shaped like the bundle PyInstaller produces."""
    monkeypatch.setattr(frozen.sys, "frozen", True, raising=False)
    monkeypatch.setattr(frozen.sys, "_MEIPASS", str(tmp_path), raising=False)
    return tmp_path


@pytest.fixture
def compiled_schema(bundle):
    """The bundle's schema directory, as the build script fills it in."""
    schemas = bundle / "share" / "glib-2.0" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "gschemas.compiled").write_bytes(b"not really, but it is there")
    return schemas


def test_a_checkout_is_not_a_bundle():
    """Nothing here is frozen, and the tests below depend on knowing that."""
    assert not frozen.is_frozen()
    assert frozen.bundle_root() is None


def test_the_bundle_root_is_where_pyinstaller_unpacked_it(bundle):
    assert frozen.is_frozen()
    assert frozen.bundle_root() == bundle


def test_glib_is_pointed_at_the_bundled_schema(compiled_schema, monkeypatch):
    """GLib finds a compiled schema nowhere near a system schema directory."""
    monkeypatch.delenv("GSETTINGS_SCHEMA_DIR", raising=False)

    frozen.configure_environment()

    assert os.environ["GSETTINGS_SCHEMA_DIR"] == str(compiled_schema)


def test_a_schema_directory_already_set_is_kept(compiled_schema, monkeypatch):
    """An override in the environment still wins; the bundle is the fallback."""
    monkeypatch.setenv("GSETTINGS_SCHEMA_DIR", "/somewhere/else")

    frozen.configure_environment()

    entries = os.environ["GSETTINGS_SCHEMA_DIR"].split(os.pathsep)
    assert entries[0] == "/somewhere/else"
    assert str(compiled_schema) in entries


def test_the_same_directory_is_not_added_twice(compiled_schema):
    """Nothing here should grow the variable every time it is asked."""
    frozen.configure_environment()
    once = os.environ["GSETTINGS_SCHEMA_DIR"]
    frozen.configure_environment()

    assert os.environ["GSETTINGS_SCHEMA_DIR"] == once


def test_a_bundle_without_a_compiled_schema_says_nothing(bundle, monkeypatch):
    """A build that forgot the schema must not claim to have one.

    config.get_settings() then raises SchemaNotInstalledError, which names the
    problem; a GSETTINGS_SCHEMA_DIR pointing at an empty directory would leave
    GLib reporting the schema missing with nothing to say about why.
    """
    monkeypatch.delenv("GSETTINGS_SCHEMA_DIR", raising=False)

    frozen.configure_environment()

    assert "GSETTINGS_SCHEMA_DIR" not in os.environ
    assert frozen.schema_dir() is None


def test_outside_a_bundle_nothing_is_touched(monkeypatch):
    """The environment of an ordinary install is not this module's business."""
    monkeypatch.setenv("GSETTINGS_SCHEMA_DIR", "/set/by/the/suite")

    frozen.configure_environment()

    assert os.environ["GSETTINGS_SCHEMA_DIR"] == "/set/by/the/suite"


# -- what the safety guard makes of a bundle -------------------------------
#
# The guard refuses the user's own store when the code is running out of a
# checkout. A bundle is the opposite of that: it is built by a release job out
# of an installed wheel, and it is the application being used.


def test_a_bundle_is_not_a_checkout(bundle):
    assert not safety.running_from_checkout()


def test_a_bundle_counts_as_installed(bundle, monkeypatch):
    """Even with no metadata to be found, which is a packaging fault, not a run.

    require_installed() exists to refuse a PYTHONPATH=src process, which is a
    thing only a developer does. Inside a bundle there is no such process to
    catch, and refusing one would take down an application a user installed.
    """
    monkeypatch.setattr(safety, "_own_distribution", lambda: None)

    safety.require_installed()


def test_the_real_store_opens_from_a_bundle(bundle, monkeypatch):
    """Which is the whole point of shipping one."""
    monkeypatch.delenv(safety.OPT_IN_VARIABLE, raising=False)

    safety.ensure_store_allowed(Path(safety.DEFAULT_STORE).expanduser())
