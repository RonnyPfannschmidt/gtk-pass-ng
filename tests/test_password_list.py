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


class TestReListingIsReconciledRatherThanRebuilt:
    """A listing that says what is already there must change nothing.

    Expansion lives on a GtkTreeListRow, and a row belongs to an item -- so a
    tree rebuilt out of new PasswordNode objects is a tree of new rows, every
    one of them collapsed. Nothing saved and replayed can put back what the
    view knew: the scroll position goes too, and one changed entry re-renders
    the whole sidebar. So the nodes that are still right are kept.
    """

    @pytest.fixture
    def stocked(self, view, backend):
        view.sync_entries(backend, ["work/mail", "work/vpn", "personal/bank"])
        return backend

    def nodes_by_name(self, view):
        found = {}

        def walk(store):
            for index in range(store.get_n_items()):
                node = store.get_item(index)
                found[node.path or node.name] = node
                walk(node.children)

        walk(view.root)
        return found

    def test_an_unchanged_listing_keeps_every_node(self, view, stocked):
        before = self.nodes_by_name(view)

        view.sync_entries(stocked, ["work/mail", "work/vpn", "personal/bank"])

        after = self.nodes_by_name(view)
        assert set(after) == set(before)
        for path, node in before.items():
            assert after[path] is node, f"{path} was replaced by a new node"

    def test_an_expanded_folder_stays_expanded_with_no_help(self, view, stocked):
        view.expand_all()
        before = visible_rows(view)

        view.sync_entries(stocked, ["work/mail", "work/vpn", "personal/bank"])

        assert visible_rows(view) == before

    def test_the_selection_survives_with_no_help(self, view, stocked):
        view.expand_all()
        view.selection.set_selected(visible_rows(view).index("vpn"))

        view.sync_entries(stocked, ["work/mail", "work/vpn", "personal/bank"])

        assert view.get_selected_password() == ("demo_1", "work/vpn")

    def test_a_changed_entry_does_not_disturb_its_neighbours(self, view, stocked):
        """Saving one password re-lists; the other rows are not involved."""
        view.expand_all()
        before = self.nodes_by_name(view)

        view.sync_entries(stocked, ["work/mail", "work/vpn", "personal/savings"])

        after = self.nodes_by_name(view)
        assert after["work/mail"] is before["work/mail"]
        assert after["work"] is before["work"]
        assert after["personal"] is before["personal"]
        assert "personal/bank" not in after
        assert "personal/savings" in after

    def test_a_new_entry_lands_in_order(self, view, stocked):
        view.expand_all()

        view.sync_entries(
            stocked, ["work/aws", "work/mail", "work/vpn", "personal/bank"]
        )

        assert visible_rows(view) == [
            "Demo",
            "personal",
            "bank",
            "work",
            "aws",
            "mail",
            "vpn",
        ]

    def test_an_emptied_folder_goes_away(self, view, stocked):
        view.expand_all()

        view.sync_entries(stocked, ["work/mail", "work/vpn"])

        assert "personal" not in visible_rows(view)

    def test_a_folder_that_became_an_entry_is_replaced(self, view, stocked):
        view.expand_all()

        view.sync_entries(stocked, ["work", "personal/bank"])

        assert view.get_selected_password() is None
        names = visible_rows(view)
        assert names.count("work") == 1
        assert "mail" not in names

    def test_a_backend_row_is_kept_across_a_reload(self, view, backend):
        view.sync_entries(backend, ["work/mail"])
        node = backend.node

        (again,) = view.sync_backends(
            [("demo_1", "Demo", "emblem-default-symbolic", "")]
        )

        assert again is backend
        assert again.node is node

    def test_a_backend_that_went_away_is_removed(self, view, backend):
        view.sync_entries(backend, ["work/mail"])
        other = view.sync_backends(
            [
                ("demo_1", "Demo", "emblem-default-symbolic", ""),
                ("demo_2", "Other", "", ""),
            ]
        )
        assert len(other) == 2

        view.sync_backends([("demo_2", "Other", "", "")])

        assert [view.root.get_item(i).name for i in range(view.root.get_n_items())] == [
            "Other"
        ]

    def test_a_renamed_backend_keeps_its_row(self, view, backend):
        view.sync_entries(backend, ["work/mail"])
        node = backend.node

        view.sync_backends([("demo_1", "Team Vault", "emblem-default-symbolic", "")])

        assert backend.node is node
        assert node.name == "Team Vault"


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

        assert list(names(view.root)) == ["Demo", "personal", "mail", "work", "mail"]

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
            "bank",
            "personal",
            "mail",
            "work",
            "mail",
            "vpn",
        ]

    def test_the_tree_goes_back_to_the_shape_it_had_before_the_search(
        self, view, stocked
    ):
        """Exactly that shape, which here is everything shut.

        A search opens what it matched. Clearing it has to close those again,
        not leave the tree hanging open at whatever the search reached -- and
        nothing in this fixture was ever opened, so nothing should be open.
        """
        view.set_filter("vpn")
        assert "vpn" in visible_rows(view)

        view.set_filter("")

        assert visible_rows(view) == ["Demo"]

    def test_what_was_open_before_the_search_is_open_after_it(self, view, stocked):
        view.expand_first_level()
        before = visible_rows(view)

        view.set_filter("vpn")
        view.set_filter("")

        assert visible_rows(view) == before

    def test_an_entry_arriving_under_a_filter_is_filtered_too(self, view, stocked):
        """Listings arrive per backend, and can land while a search is running."""
        view.set_filter("vpn")

        view.add_password(stocked, "later/vpn-two")
        view.add_password(stocked, "later/unrelated")

        assert list(names(view.root)) == ["Demo", "later", "vpn-two", "work", "vpn"]

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
