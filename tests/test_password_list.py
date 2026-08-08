"""The sidebar tree: what ends up in it, and what selecting a row reports.

The widget owns a model of :class:`PasswordNode` objects; the ColumnView is a
view onto it. These tests work against that model, because it is what the
window populates and what selection reads back.
"""

import time

import pytest

from gtkpass._gi import Adw, GLib, Gtk
from gtkpass.ui.password_list import PasswordTreeView

pytestmark = pytest.mark.gui


@pytest.fixture(scope="session", autouse=True)
def adwaita():
    """Initialise libadwaita once; widget construction needs it."""
    Adw.init()


@pytest.fixture
def view():
    return PasswordTreeView()


@pytest.fixture
def backend(view):
    return view.add_backend("demo_1", "Demo", "emblem-default-symbolic")


def names(store):
    """Every node name in the tree, depth first."""
    for index in range(store.get_n_items()):
        node = store.get_item(index)
        yield node.name
        yield from names(node.children)


def visible_rows(view):
    """Names the view would actually render, honouring expansion state."""
    model = view.tree_model
    return [
        model.get_row(index).get_item().name for index in range(model.get_n_items())
    ]


class TestStructure:
    def test_a_backend_becomes_a_root_row(self, view, backend):
        assert list(names(view.root)) == ["Demo"]

    def test_an_entry_hangs_under_its_backend(self, view, backend):
        view.add_password(backend, "email")

        assert list(names(view.root)) == ["Demo", "email"]

    def test_a_path_becomes_nested_folders(self, view, backend):
        view.add_password(backend, "work/mail/imap")

        assert list(names(view.root)) == ["Demo", "work", "mail", "imap"]

    def test_entries_in_one_folder_share_a_single_folder_row(self, view, backend):
        view.add_password(backend, "work/alpha")
        view.add_password(backend, "work/beta")

        assert list(names(view.root)) == ["Demo", "work", "alpha", "beta"]

    def test_two_backends_stay_separate(self, view, backend):
        other = view.add_backend("demo_2", "Other", "")
        view.add_password(backend, "mine")
        view.add_password(other, "theirs")

        assert list(names(view.root)) == ["Demo", "mine", "Other", "theirs"]

    def test_clear_all_empties_the_tree(self, view, backend):
        view.add_password(backend, "email")

        view.clear_all()

        assert list(names(view.root)) == []


class TestExpansion:
    def test_children_are_hidden_until_expanded(self, view, backend):
        view.add_password(backend, "email")

        assert visible_rows(view) == ["Demo"]

    def test_expanding_the_first_level_reveals_the_entries(self, view, backend):
        view.add_password(backend, "email")

        view.expand_first_level()

        assert visible_rows(view) == ["Demo", "email"]

    def test_a_folder_stays_collapsed_under_an_expanded_backend(self, view, backend):
        view.add_password(backend, "work/mail")

        view.expand_first_level()

        assert visible_rows(view) == ["Demo", "work"]


class TestIcons:
    """What a row is has to be readable at a glance, not inferred from depth."""

    def icon_of(self, view, name):
        for index in range(view.tree_model.get_n_items()):
            node = view.tree_model.get_row(index).get_item()
            if node.name == name:
                return node.icon_name
        raise AssertionError(f"no row named {name}")

    def test_an_entry_gets_the_password_icon(self, view, backend):
        view.add_password(backend, "email")
        view.expand_all()

        assert self.icon_of(view, "email") == "dialog-password-symbolic"

    def test_a_folder_gets_the_folder_icon(self, view, backend):
        view.add_password(backend, "work/mail")
        view.expand_all()

        assert self.icon_of(view, "work") == "folder-symbolic"

    def test_a_backend_keeps_the_icon_it_was_given(self, view, backend):
        assert self.icon_of(view, "Demo") == "emblem-default-symbolic"


def present(view, ready):
    """Present the view until ``ready(view)`` holds, or the deadline passes.

    Bounded by wall clock and not by iteration count: rows are built during a
    layout pass, and a non-blocking iteration returns immediately when nothing
    is pending, so a plain loop spins through before the view has drawn.
    Waiting on the condition rather than on a fixed delay is also what keeps
    this from failing on a loaded machine.
    """
    window = Gtk.Window(child=view, default_width=300, default_height=400)
    window.present()

    context = GLib.MainContext.default()
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not ready(view):
        context.iteration(may_block=False)
        time.sleep(0.005)
    return window


def rendered_rows(view):
    """The row widgets the view has built, if any."""
    return [
        child
        for child in descendants(view.column_view)
        if child.__gtype__.name == "GtkColumnViewRowWidget" and child.get_height()
    ]


def descendants(widget):
    """Every widget below ``widget``, depth first."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


class TestRendering:
    """The row template is only exercised once rows are actually built.

    Everything above works on the model, which a broken binding expression in
    password_list.blp would not disturb: the tree would be right and the
    sidebar empty.
    """

    def labels(self, view):
        return {
            child.get_text()
            for child in descendants(view.column_view)
            if isinstance(child, Gtk.Label)
        }

    def icons(self, view):
        return {
            child.get_icon_name()
            for child in descendants(view.column_view)
            if isinstance(child, Gtk.Image)
        }

    def test_a_row_shows_its_name(self, view, backend):
        view.add_password(backend, "email")
        view.expand_first_level()

        present(view, lambda v: {"Demo", "email"} <= self.labels(v))

        assert {"Demo", "email"} <= self.labels(view)

    def test_a_row_shows_its_icon(self, view, backend):
        view.add_password(backend, "email")
        view.expand_first_level()

        present(view, lambda v: "dialog-password-symbolic" in self.icons(v))

        assert "dialog-password-symbolic" in self.icons(view)


class TestCompactness:
    """A sidebar of one column has no room to spend on chrome.

    Both of these are about pixels the tree gives back: the header of a column
    that needs no title, and the padding a full-size list row carries.
    """

    def test_no_column_header_is_shown(self, view, backend):
        view.add_password(backend, "email")
        view.expand_first_level()
        present(view, rendered_rows)

        assert not view.column_view.get_first_child().get_visible()

    def test_rows_are_tighter_than_a_default_list_row(self, view, backend):
        view.add_password(backend, "email")
        view.expand_first_level()
        present(view, rendered_rows)

        # A stock ColumnView row is 34px tall for this content; the compact
        # style class takes it to 22. The padding sits on the row, not on the
        # cell inside it, which stays 18px either way.
        heights = [row.get_height() for row in rendered_rows(view)]
        assert heights and max(heights) < 30


class TestSelection:
    def select(self, view, name):
        """Select the visible row called ``name``."""
        view.expand_all()
        view.selection.set_selected(visible_rows(view).index(name))

    def test_nothing_is_selected_to_begin_with(self, view, backend):
        assert view.get_selected_password() is None

    def test_selecting_a_backend_reports_no_password(self, view, backend):
        view.add_password(backend, "email")

        self.select(view, "Demo")

        assert view.get_selected_password() is None

    def test_selecting_a_folder_reports_no_password(self, view, backend):
        view.add_password(backend, "work/mail")

        self.select(view, "work")

        assert view.get_selected_password() is None

    def test_selecting_an_entry_reports_its_backend_and_full_path(self, view, backend):
        view.add_password(backend, "work/mail")

        self.select(view, "mail")

        assert view.get_selected_password() == ("demo_1", "work/mail")

    def test_the_callback_fires_for_an_entry(self, view, backend):
        view.add_password(backend, "email")
        seen = []
        view.connect_password_selected(lambda *args: seen.append(args))

        self.select(view, "email")

        assert seen == [("demo_1", "email")]

    def test_the_callback_stays_quiet_for_a_backend_row(self, view, backend):
        view.add_password(backend, "email")
        seen = []
        view.connect_password_selected(lambda *args: seen.append(args))

        self.select(view, "Demo")

        assert seen == []
