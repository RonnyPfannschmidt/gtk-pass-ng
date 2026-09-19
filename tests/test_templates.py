"""Checks that the compiled UI definitions still match the Python that binds them.

When a widget is renamed in a ``.blp`` but not in its class, PyGObject leaves the
corresponding attribute as ``None`` instead of failing.  The application then
half-works: it starts, and blows up later on whichever code path touches the
missing widget.  These tests turn that into an import-time-ish failure.
"""

import pytest

from gtkpass._gi import Adw
from gtkpass.ui.password_detail import PasswordDetailView
from gtkpass.ui.password_edit import PasswordEditDialog
from gtkpass.ui.password_generator import PasswordGeneratorGroup
from gtkpass.ui.password_list import PasswordTreeView
from gtkpass.ui.password_rename import PasswordRenameDialog
from gtkpass.ui.password_rotate import PasswordRotateDialog

pytestmark = pytest.mark.gui

#: Widgets that can be built standalone, without an application or a parent.
STANDALONE_WIDGETS = [
    PasswordTreeView,
    PasswordDetailView,
    PasswordEditDialog,
    PasswordRenameDialog,
    PasswordGeneratorGroup,
    PasswordRotateDialog,
]


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


class TestSyncButtonStack:
    """The sync button swaps icon for spinner by page name.

    Renaming a page makes set_visible_child_name a silent no-op, so the button
    would simply never show that a sync was running.
    """

    @pytest.mark.parametrize("page_name", ["idle", "busy"])
    def test_stack_page_exists(self, page_name):
        from gtkpass.window import GTKPassWindow

        outcome = {}

        def on_activate(app):
            window = GTKPassWindow(application=app)
            outcome["child"] = window.sync_stack.get_child_by_name(page_name)
            window.close()
            app.quit()

        app = Adw.Application(application_id="io.github.RonnyPfannschmidt.GTKPass.Test")
        app.connect("activate", on_activate)
        app.run([])

        assert outcome.get("child") is not None, (
            f"window.blp has no Stack page named {page_name!r}; "
            f"set_visible_child_name({page_name!r}) is a silent no-op"
        )


class TestTheErrorDetailDialog:
    """A builder object rather than a template: Adw.AlertDialog is final.

    So the standalone-template sweep above cannot cover it, and nothing else
    would notice the label being renamed out from under the window -- which
    would leave the Details button opening an empty dialog at exactly the
    moment somebody needed to read something.
    """

    def built(self):
        import importlib.resources

        from gtkpass._gi import Gtk

        return Gtk.Builder.new_from_file(
            str(importlib.resources.files("gtkpass.ui.blueprints") / "error_detail.ui")
        )

    def test_the_dialog_is_there_under_the_name_the_window_looks_up(self):
        assert self.built().get_object("error_detail_dialog") is not None

    def test_the_label_is_there_under_the_name_the_window_fills_in(self):
        assert self.built().get_object("error_detail_label") is not None

    def test_the_error_can_be_selected_to_be_pasted_into_a_report(self):
        assert self.built().get_object("error_detail_label").get_selectable()

    def test_a_long_error_scrolls_rather_than_growing_the_dialog(self):
        """gpg can be verbose, and a dialog taller than the screen puts its
        Close button somewhere there is no room for it."""
        scroller = self.built().get_object("error_detail_scroller")

        assert scroller is not None
        assert scroller.get_max_content_height() > 0
        assert scroller.get_propagate_natural_height(), (
            "a short error would otherwise sit in a box the height of a long one"
        )


def icons_named_in_blueprints() -> list[str]:
    """Every icon-name literal in the .blp files, once each."""
    import re
    from pathlib import Path

    blueprints = Path(__file__).resolve().parent.parent / "src/gtkpass/ui/blueprints"
    found = set()
    for source in blueprints.glob("*.blp"):
        found.update(re.findall(r'icon-name:\s*"([^"]+)"', source.read_text()))
    return sorted(found)


class TestEveryIconExists:
    """An icon the theme does not have is drawn as a broken-image glyph.

    external-link-symbolic went out of adwaita-icon-theme, and the Open
    button in the rotation wizard has been a grey smudge since. Nothing said
    so: GTK draws a placeholder and moves on.
    """

    @pytest.mark.parametrize("icon_name", icons_named_in_blueprints())
    def test_the_theme_has_it(self, icon_name):
        from gtkpass._gi import Gdk, Gtk

        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())

        assert theme.has_icon(icon_name), f"no icon named {icon_name!r}"
