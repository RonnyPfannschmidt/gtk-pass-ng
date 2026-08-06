"""Checks that the compiled UI definitions still match the Python that binds them.

When a widget is renamed in a ``.blp`` but not in its class, PyGObject leaves the
corresponding attribute as ``None`` instead of failing.  The application then
half-works: it starts, and blows up later on whichever code path touches the
missing widget.  These tests turn that into an import-time-ish failure.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import pytest
from gi.repository import Adw, Gtk  # noqa: E402

from gtkpass.ui.password_detail import PasswordDetailView
from gtkpass.ui.password_list import PasswordTreeView

pytestmark = pytest.mark.gui

#: Widgets that can be built standalone, without an application or a parent.
STANDALONE_WIDGETS = [PasswordTreeView, PasswordDetailView]


def declared_children(widget_class):
    """Names the class binds via ``Gtk.Template.Child()``."""
    return sorted(getattr(widget_class, "__gtktemplate_widgets__", {}))


@pytest.fixture(scope="session", autouse=True)
def adwaita():
    """Initialise libadwaita once; widget construction needs it."""
    Adw.init()


@pytest.mark.parametrize(
    "widget_class", STANDALONE_WIDGETS, ids=lambda cls: cls.__name__
)
class TestStandaloneTemplates:
    def test_declares_children(self, widget_class):
        """A template class that binds nothing is a sign the decorator misfired."""
        assert declared_children(widget_class)

    def test_every_declared_child_resolves(self, widget_class):
        widget = widget_class()
        unresolved = [
            name
            for name in declared_children(widget_class)
            if getattr(widget, name, None) is None
        ]
        assert unresolved == [], (
            f"{widget_class.__name__} declares children that are missing from "
            f"its .ui file: {unresolved}"
        )


class TestPasswordDetailStack:
    """The detail view switches by page name, so the names have to exist."""

    @pytest.mark.parametrize("page_name", ["loading", "content"])
    def test_stack_page_exists(self, page_name):
        view = PasswordDetailView()
        assert view.stack.get_child_by_name(page_name) is not None, (
            f"password_detail.blp has no Stack page named {page_name!r}; "
            f"set_visible_child_name({page_name!r}) is a silent no-op"
        )


class TestMainWindow:
    """The window needs a real application to be constructed."""

    def test_children_resolve_on_activate(self):
        from gtkpass.window import GTKPassWindow

        outcome = {}

        def on_activate(app):
            window = GTKPassWindow(application=app)
            outcome["unresolved"] = [
                name
                for name in declared_children(GTKPassWindow)
                if getattr(window, name, None) is None
            ]
            window.close()
            app.quit()

        app = Adw.Application(application_id="io.github.RonnyPfannschmidt.GTKPass.Test")
        app.connect("activate", on_activate)
        app.run([])

        assert outcome, "the application never activated"
        assert outcome["unresolved"] == []
