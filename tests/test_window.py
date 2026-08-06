"""End-to-end checks for the main window.

These cover the path a user actually takes: configure a backend, expect to see
its passwords.  That path was silently broken for months because nothing
exercised it.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pytest
from gi.repository import Adw, GLib  # noqa: E402

from gtkpass.config import get_settings

pytestmark = pytest.mark.gui


def run_in_application(callback):
    """Activate a real application, run ``callback(app)``, and return its result."""
    captured = {}

    def on_activate(app):
        try:
            captured["value"] = callback(app)
        finally:
            app.quit()

    app = Adw.Application(application_id="io.github.RonnyPfannschmidt.GTKPass.Test")
    app.connect("activate", on_activate)
    app.run([])

    assert "value" in captured, "the application never activated"
    return captured["value"]


def walk_tree(model, parent=None):
    """Yield every row of a Gtk.TreeModel depth first."""
    row = model.iter_children(parent)
    while row is not None:
        yield row
        yield from walk_tree(model, row)
        row = model.iter_next(row)


#: Matches the ``<type>_<timestamp>`` form the settings UI generates, so the
#: display-name derivation is exercised the way it runs in production.
DEMO_BACKEND_ID = "demo_1766234611"


@pytest.fixture
def demo_backend_configured():
    """Point the application's settings at a single demo backend."""
    settings = get_settings()
    previous = settings.get_value("backend-instances")
    settings.set_value(
        "backend-instances", GLib.Variant("a(ss)", [(DEMO_BACKEND_ID, "demo")])
    )
    yield
    settings.set_value("backend-instances", previous)


class TestWindowWithoutBackends:
    def test_prompts_for_configuration(self):
        from gtkpass.window import GTKPassWindow

        title = run_in_application(
            lambda app: GTKPassWindow(application=app).placeholder_page.get_title()
        )

        assert title == "No Backends Configured"


class TestWindowWithDemoBackend:
    @pytest.fixture
    def rows(self, demo_backend_configured):
        from gtkpass.window import GTKPassWindow

        def collect(app):
            window = GTKPassWindow(application=app)
            model = window.password_list.tree_view.get_model()
            return [
                model.get_value(row, window.password_list.COL_NAME)
                for row in walk_tree(model)
            ]

        return run_in_application(collect)

    def test_backend_appears_in_the_sidebar(self, rows):
        assert "Demo" in rows

    def test_demo_passwords_are_listed(self, rows):
        """The demo backend ships sample entries; they must reach the tree."""
        assert len(rows) > 1, f"only the backend row was added: {rows}"

    def test_no_backend_is_marked_unavailable(self, rows):
        assert not [row for row in rows if "unavailable" in row]
