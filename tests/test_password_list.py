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


class TestExpansionSurvivesARebuild:
    """The tree is thrown away and rebuilt after every write and every sync.

    Saving an entry, adding one, deleting one and syncing all re-list, and a
    re-listing used to come back with every folder shut -- so the reward for
    saving a password three levels down was finding your way back to it.
    """

    @pytest.fixture
    def stocked(self, view, backend):
        for path in ("work/mail/imap", "work/vpn", "personal/bank"):
            view.add_password(backend, path)
        return backend

    def rebuild(self, view, paths=("work/mail/imap", "work/vpn", "personal/bank")):
        """What the window does when a listing comes back."""
        view.clear_all()
        record = view.add_backend("demo_1", "Demo", "emblem-default-symbolic")
        for path in paths:
            view.add_password(record, path)
        view.restore_expansion()
        return record

    def test_an_expanded_folder_is_still_expanded(self, view, stocked):
        view.expand_all()
        before = visible_rows(view)

        self.rebuild(view)

        assert visible_rows(view) == before

    def test_a_closed_folder_stays_closed(self, view, stocked):
        view.expand_first_level()
        before = visible_rows(view)

        self.rebuild(view)

        assert visible_rows(view) == before
        assert "imap" not in visible_rows(view)

    def test_one_open_folder_does_not_open_its_neighbour(self, view, stocked):
        view.expand_first_level()
        # Open work/, leave personal/ shut.
        row = next(
            view.tree_model.get_row(index)
            for index in range(view.tree_model.get_n_items())
            if view.tree_model.get_row(index).get_item().name == "work"
        )
        row.set_expanded(True)

        self.rebuild(view)

        assert "mail" in visible_rows(view)
        assert "bank" not in visible_rows(view)

    def test_a_collapsed_backend_stays_collapsed(self, view, stocked):
        view.expand_first_level()
        view.tree_model.get_row(0).set_expanded(False)

        self.rebuild(view)

        assert visible_rows(view) == ["Demo"]

    def test_a_folder_that_is_gone_is_not_missed(self, view, stocked):
        """Deleting the last entry in a folder takes the folder with it."""
        view.expand_all()

        self.rebuild(view, paths=("personal/bank",))

        assert visible_rows(view) == ["Demo", "personal", "bank"]

    def test_a_new_folder_is_not_opened_by_a_neighbour(self, view, stocked):
        view.expand_first_level()

        self.rebuild(view, paths=("personal/bank", "later/added"))

        assert "added" not in visible_rows(view)


class TestFiltering:
    """The sidebar is filtered by rebuilding it, not by hiding rows.

    A GtkFilterListModel over the tree can only see rows that have been
    materialised, and a TreeListModel materialises a folder's children only
    once it is expanded -- so a filter laid over the view would have matched
    whatever happened to be open and nothing else.
    """

    @pytest.fixture
    def stocked(self, view, backend):
        for path in ("work/mail", "work/vpn", "personal/mail", "bank"):
            view.add_password(backend, path)
        return backend

    def test_no_filter_shows_everything(self, view, stocked):
        view.set_filter("")

        assert set(names(view.root)) == {
            "Demo",
            "work",
            "mail",
            "vpn",
            "personal",
            "bank",
        }

    def test_a_filter_keeps_only_matching_entries(self, view, stocked):
        view.set_filter("vpn")

        assert list(names(view.root)) == ["Demo", "work", "vpn"]

    def test_matching_is_case_insensitive(self, view, stocked):
        view.set_filter("VPN")

        assert list(names(view.root)) == ["Demo", "work", "vpn"]

    def test_a_folder_name_matches_everything_below_it(self, view, stocked):
        view.set_filter("work/")

        assert list(names(view.root)) == ["Demo", "work", "mail", "vpn"]

    def test_matches_in_two_folders_keep_both(self, view, stocked):
        view.set_filter("mail")

        assert list(names(view.root)) == ["Demo", "work", "mail", "personal", "mail"]

    def test_matches_are_visible_without_expanding(self, view, stocked):
        """A match inside a collapsed folder is a match nobody can see."""
        view.set_filter("vpn")

        assert visible_rows(view) == ["Demo", "work", "vpn"]

    def test_a_backend_with_no_matches_is_dropped(self, view, stocked):
        other = view.add_backend("demo_2", "Other", "")
        view.add_password(other, "unrelated")

        view.set_filter("vpn")

        assert "Other" not in list(names(view.root))

    def test_nothing_matching_empties_the_tree(self, view, stocked):
        view.set_filter("nothing here")

        assert list(names(view.root)) == []

    def test_the_count_of_matches_is_reported(self, view, stocked):
        """The window needs it to tell an empty store from an empty search."""
        assert view.set_filter("mail") == 2
        assert view.set_filter("nothing here") == 0

    def test_clearing_the_filter_brings_everything_back(self, view, stocked):
        view.set_filter("vpn")

        view.set_filter("")

        assert list(names(view.root)) == [
            "Demo",
            "work",
            "mail",
            "vpn",
            "personal",
            "mail",
            "bank",
        ]

    def test_folders_are_closed_again_once_the_filter_clears(self, view, stocked):
        view.set_filter("vpn")

        view.set_filter("")

        assert visible_rows(view) == ["Demo", "work", "personal", "bank"]

    def test_an_entry_arriving_under_a_filter_is_filtered_too(self, view, stocked):
        """Listings arrive per backend, and can land while a search is running."""
        view.set_filter("vpn")

        view.add_password(stocked, "later/vpn-two")
        view.add_password(stocked, "later/unrelated")

        assert list(names(view.root)) == ["Demo", "work", "vpn", "later", "vpn-two"]

    def test_a_backend_added_under_a_filter_waits_for_a_match(self, view, stocked):
        view.set_filter("vpn")
        other = view.add_backend("demo_2", "Other", "")

        assert "Other" not in list(names(view.root))

        view.add_password(other, "office/vpn")

        assert list(names(view.root)) == [
            "Demo",
            "work",
            "vpn",
            "Other",
            "office",
            "vpn",
        ]

    def test_clear_all_forgets_the_entries_behind_the_filter(self, view, stocked):
        view.clear_all()

        view.set_filter("")

        assert list(names(view.root)) == []


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


class TestTheContextMenu:
    """Right-click, and press-and-hold, offer the entry actions on the row.

    The menu items are window actions, so what the tree is responsible for is
    narrow: pick the row that was clicked, and put the menu over it.
    """

    def test_the_menu_is_parented_to_the_tree(self, view, backend):
        assert view._menu.get_parent() is view

    def test_its_items_are_window_actions(self, view, backend):
        model = view._menu.get_menu_model()
        actions = []
        for section in range(model.get_n_items()):
            links = model.get_item_link(section, "section")
            for index in range(links.get_n_items()):
                actions.append(
                    links.get_item_attribute_value(index, "action").get_string()
                )

        assert actions == [
            "win.copy-password",
            "win.copy-username",
            "win.edit-password",
            "win.delete-password",
        ]

    def test_a_click_selects_the_row_under_it(self, view, backend):
        for path in ("alpha", "beta", "gamma"):
            view.add_password(backend, path)
        view.expand_first_level()
        window = present(view, rendered_rows)

        # Half way down the second row, counting the backend heading as the
        # first. The column header is hidden, so the rows start at the top.
        view._popup_at(10.0, view._row_height() * 1.5)

        assert view.get_selected_password() == ("demo_1", "alpha")
        window.destroy()

    def test_a_click_past_the_last_row_selects_nothing(self, view, backend):
        view.add_password(backend, "alpha")
        view.expand_first_level()
        window = present(view, rendered_rows)

        view._popup_at(10.0, view.get_height() - 1)

        assert view.get_selected_password() is None
        window.destroy()

    def test_an_empty_tree_offers_no_menu(self, view):
        view._popup_at(10.0, 10.0)

        assert not view._menu.is_visible()


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
