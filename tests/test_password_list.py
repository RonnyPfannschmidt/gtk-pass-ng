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


class TestRendering:
    """The row template is only exercised once rows are actually built.

    Everything above works on the model, which a broken binding expression in
    password_list.blp would not disturb: the tree would be right and the
    sidebar empty.
    """

    def labels(self, widget):
        """Text of every Label below ``widget``."""
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label):
                yield child.get_text()
            yield from self.labels(child)
            child = child.get_next_sibling()

    def rendered(self, view):
        """Present the view long enough for it to build its rows."""
        window = Gtk.Window(child=view)
        window.present()

        context = GLib.MainContext.default()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            context.iteration(may_block=False)
            texts = set(self.labels(view.column_view))
            if len(texts) > 1:  # more than the column header
                return texts
            time.sleep(0.005)
        return set(self.labels(view.column_view))

    def test_a_row_shows_its_name(self, view, backend):
        view.add_password(backend, "email")
        view.expand_first_level()

        assert {"Demo", "email"} <= self.rendered(view)


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
