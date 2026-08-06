"""End-to-end checks for the main window.

These cover the path a user actually takes: configure a backend, expect to see
its passwords.  That path was silently broken for months because nothing
exercised it.
"""

import pytest

from gtkpass._gi import Adw, GLib
from gtkpass.config import get_settings, set_backend_display_name

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


class TestRenaming:
    """A backend renamed in the settings dialog must reach the sidebar.

    The rename writes the instance's own display-name key and never touches
    backend-instances, so watching only the latter left the old label in place.
    """

    @pytest.fixture
    def named_demo(self, demo_backend_configured):
        set_backend_display_name("demo", DEMO_BACKEND_ID, "My Vault")
        yield
        set_backend_display_name("demo", DEMO_BACKEND_ID, "")

    def sidebar_names(self, window):
        model = window.password_list.tree_view.get_model()
        return [
            model.get_value(row, window.password_list.COL_NAME)
            for row in walk_tree(model)
        ]

    def test_a_stored_name_is_shown(self, named_demo):
        from gtkpass.window import GTKPassWindow

        names = run_in_application(
            lambda app: self.sidebar_names(GTKPassWindow(application=app))
        )

        assert "My Vault" in names

    def test_renaming_updates_an_open_window(self, demo_backend_configured):
        from gtkpass.window import GTKPassWindow

        def rename_while_open(app):
            window = GTKPassWindow(application=app)
            assert "Demo" in self.sidebar_names(window)

            set_backend_display_name("demo", DEMO_BACKEND_ID, "Renamed Live")
            try:
                return self.sidebar_names(window)
            finally:
                set_backend_display_name("demo", DEMO_BACKEND_ID, "")

        assert "Renamed Live" in run_in_application(rename_while_open)
