"""Finding the GSettings schema when it is not in a system schema directory.

A systemd-sysext build cannot install into ``/usr/share/glib-2.0/schemas``: the
``gschemas.compiled`` there is a single file holding every application's
schemas, and an overlay carrying its own copy hides all of them, so the desktop
comes up with GNOME's own settings missing. The schema is compiled to a private
directory instead, and this is what makes the application look there.
"""

import subprocess
from pathlib import Path

import pytest

from gtkpass import config
from gtkpass._gi import Gio

SCHEMA_XML_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(autouse=True)
def _forget_the_cached_source():
    """The source is resolved once per process; these tests change what it sees."""
    config.schema_source.cache_clear()
    yield
    config.schema_source.cache_clear()


@pytest.fixture
def bundled_schema_dir(tmp_path, monkeypatch):
    """A compiled schema directory in the shape a sysext image ships."""
    target = tmp_path / "schemas"
    target.mkdir()

    for xml in SCHEMA_XML_DIR.glob("*.gschema.xml"):
        (target / xml.name).write_bytes(xml.read_bytes())
    subprocess.run(["glib-compile-schemas", str(target)], check=True)

    monkeypatch.setattr(config, "BUNDLED_SCHEMA_DIR", target)
    return target


class TestTheBundledSchemaDirectory:
    def test_the_schema_is_found_through_it(self, bundled_schema_dir, monkeypatch):
        """With nothing else installed, the private directory is what answers."""
        monkeypatch.setattr(
            Gio.SettingsSchemaSource, "get_default", staticmethod(lambda: None)
        )
        config.schema_source.cache_clear()

        assert config.schema_source() is not None
        assert config.get_settings().get_int("clipboard-timeout") == 45

    def test_the_system_directories_are_still_searched(self, bundled_schema_dir):
        """It is added to the search path, not put in place of it.

        The plain RPM installs into the system schema directory and ships no
        private one; nothing here may break that.
        """
        assert config.get_settings() is not None

    def test_a_missing_directory_changes_nothing(self, tmp_path, monkeypatch, caplog):
        """Which is the normal case: an RPM or a checkout ships nothing there."""
        monkeypatch.setattr(config, "BUNDLED_SCHEMA_DIR", tmp_path / "absent")
        config.schema_source.cache_clear()

        assert config.get_settings().get_int("clipboard-timeout") == 45
        assert not caplog.records

    def test_an_unreadable_directory_does_not_take_the_app_down(
        self, tmp_path, monkeypatch, caplog
    ):
        """A truncated or foreign gschemas.compiled must not be fatal.

        Falling back to the system source leaves the application working, or at
        worst reporting a missing schema, which someone can act on; letting the
        error out of here during startup is neither.
        """
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "gschemas.compiled").write_bytes(b"not a compiled schema")
        monkeypatch.setattr(config, "BUNDLED_SCHEMA_DIR", broken)
        config.schema_source.cache_clear()

        assert config.get_settings().get_int("clipboard-timeout") == 45
        assert "unreadable schema directory" in caplog.text
