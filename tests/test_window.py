"""End-to-end checks for the main window.

These cover the path a user actually takes: configure a backend, expect to see
its passwords.  That path was silently broken for months because nothing
exercised it.
"""

import itertools
import logging
import threading
import time

import pytest

from gtkpass._gi import Adw, GLib
from gtkpass.config import get_settings, set_backend_display_name

pytestmark = pytest.mark.gui


#: Bumped per application built below, so that no two share an id.
_run = itertools.count()


def run_in_application(callback):
    """Activate a real application, run ``callback(app)``, and return its result.

    Each one gets an id of its own. A GApplication registers its id on the
    session bus, and a second one claiming an id that is still registered
    becomes a *remote* instance of the first: it forwards its activation and
    never activates locally, so the callback never runs and the failure lands
    on whichever test came next rather than on the one that held the id.
    Nothing here shares state between runs, so nothing wants the id shared.
    """
    captured = {}

    def on_activate(app):
        try:
            captured["value"] = callback(app)
        finally:
            app.quit()

    app = Adw.Application(
        application_id=f"io.github.RonnyPfannschmidt.GTKPass.Test{next(_run)}"
    )
    app.connect("activate", on_activate)
    app.run([])

    assert "value" in captured, "the application never activated"
    return captured["value"]


def pump_until(condition, timeout_seconds: float = 10.0):
    """Run the main loop until ``condition`` holds, or the deadline passes.

    Background decryption delivers its result through GLib.idle_add, so the
    loop has to turn before anything reaches the widgets. Bound this by wall
    clock rather than by iteration count: a non-blocking iteration returns
    immediately when nothing is pending, so a plain loop spins through long
    before a worker thread has finished.
    """
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        context.iteration(may_block=False)
        time.sleep(0.005)
    return condition()


def loaded_window(app, backend_id=None):
    """A window whose backends have finished loading.

    Constructing one only starts the load: building a backend runs git over the
    store and opens a D-Bus connection, which is why it happens on the manager's
    pool rather than in __init__. So every test that wants a backend has to turn
    the main loop until it arrives, and this is the one place that waits.
    """
    from gtkpass.window import GTKPassWindow

    window = GTKPassWindow(application=app)
    wanted = backend_id or DEMO_BACKEND_ID
    assert pump_until(lambda: window.backend_manager.get_backend(wanted) is not None), (
        f"the {wanted} backend never finished loading"
    )
    return window


def listed_window(app, backend_id=None):
    """A loaded window whose sidebar has its entries in it as well.

    Listing is a second round trip after the backend is built, so a test that
    reads the tree has to wait for that too.
    """
    window = loaded_window(app, backend_id)
    assert pump_until(lambda: window._pending_listings == 0), (
        "the sidebar never finished filling in"
    )
    return window


def sidebar_names(window):
    """Every name in the sidebar tree, depth first."""

    def walk(store):
        for index in range(store.get_n_items()):
            node = store.get_item(index)
            yield node.name
            yield from walk(node.children)

    return list(walk(window.password_list.root))


def displayed_name(window):
    """The entry the detail pane is showing, read back off its heading.

    The pane splits a path across two labels, so put it back together rather
    than asking the view which entry it holds: what these tests are after is
    that the right one reached the display. The folder label carries the
    separator, so the two concatenate as they read.
    """
    detail = window.password_detail
    folder = detail.path_label.get_text() if detail.path_label.get_visible() else ""
    return folder + detail.title_label.get_text()


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

    def test_the_preferences_button_is_offered(self):
        from gtkpass.window import GTKPassWindow

        visible = run_in_application(
            lambda app: GTKPassWindow(
                application=app
            ).open_preferences_button.get_visible()
        )

        assert visible


class TestTheFirstRunOffersAStoreThatIsAlreadyThere:
    """It used to hand the user a preferences dialog and four type names.

    Somebody who already uses `pass` wants a window onto the store they have,
    and GTKPass can see that it is there.
    """

    @pytest.fixture
    def no_backends(self):
        settings = get_settings()
        previous = settings.get_value("backend-instances")
        settings.set_value("backend-instances", GLib.Variant("a(ss)", []))
        yield settings
        settings.set_value("backend-instances", previous)

    @pytest.fixture
    def store(self, tmp_path, monkeypatch, no_backends):
        """A store to be found, marked as scratch so the guard allows it."""
        from gtkpass.firstrun import STORE_MARKER
        from gtkpass.safety import SCRATCH_MARKER

        store = tmp_path / ".password-store"
        store.mkdir()
        (store / STORE_MARKER).write_text("ABCDEF01\n")
        (store / SCRATCH_MARKER).touch()
        monkeypatch.setenv("PASSWORD_STORE_DIR", str(store))
        return store

    def test_a_store_that_is_there_is_offered(self, store):
        from gtkpass.window import GTKPassWindow

        def offered(app):
            window = GTKPassWindow(application=app)
            return (
                window._placeholder_state,
                window.adopt_store_button.get_visible(),
                window.adopt_store_button.get_label(),
            )

        state, visible, label = run_in_application(offered)

        assert state == "found-store"
        assert visible
        assert str(store) in label or ".password-store" in label

    def test_nothing_is_offered_when_there_is_no_store(
        self, tmp_path, monkeypatch, no_backends
    ):
        from gtkpass.window import GTKPassWindow

        monkeypatch.setenv("PASSWORD_STORE_DIR", str(tmp_path / "absent"))

        def offered(app):
            window = GTKPassWindow(application=app)
            return window._placeholder_state, window.adopt_store_button.get_visible()

        state, visible = run_in_application(offered)

        assert state == "no-backends"
        assert visible is False

    def test_accepting_it_records_a_backend_for_it(self, store, no_backends):
        from gtkpass.window import GTKPassWindow

        def adopt(app):
            window = GTKPassWindow(application=app)
            window.activate_action("win.adopt-store", None)
            return list(no_backends.get_value("backend-instances"))

        recorded = run_in_application(adopt)

        assert len(recorded) == 1
        backend_id, backend_type = recorded[0]
        assert backend_type in ("pass", "direct")
        assert backend_id.startswith(backend_type)

    def test_the_recorded_backend_points_at_the_store(self, store, no_backends):
        from gtkpass.config import get_backend_settings
        from gtkpass.window import GTKPassWindow

        def adopt(app):
            window = GTKPassWindow(application=app)
            window.activate_action("win.adopt-store", None)
            (recorded,) = list(no_backends.get_value("backend-instances"))
            backend_id, backend_type = recorded
            return get_backend_settings(backend_type, backend_id).get_string(
                "password-store-dir"
            )

        assert run_in_application(adopt) == str(store)

    def test_the_offer_goes_away_once_it_is_taken(self, store, no_backends):
        from gtkpass.window import GTKPassWindow

        def adopt(app):
            window = GTKPassWindow(application=app)
            window.activate_action("win.adopt-store", None)
            return window.adopt_store_button.get_visible()

        assert run_in_application(adopt) is False


class TestThePlaceholderSaysWhichStateItIsIn:
    """One status page served four situations by being written over in place.

    Whatever it had last been set to was what the next situation showed. A
    window with entries in the sidebar and nothing selected still read
    "Loading...", and a failed decrypt dropped the user onto a page announcing
    "No Passwords Found" while the passwords sat in the sidebar beside it.
    """

    def test_listed_entries_invite_a_selection(self, demo_backend_configured):
        def state(app):
            window = listed_window(app)
            return window._placeholder_state, window.placeholder_page.get_title()

        state_name, title = run_in_application(state)

        assert state_name == "ready"
        assert "Loading" not in title

    def test_the_preferences_button_goes_away_once_a_backend_loads(
        self, demo_backend_configured
    ):
        def visible(app):
            return listed_window(app).open_preferences_button.get_visible()

        assert run_in_application(visible) is False

    def test_a_failed_open_says_so_rather_than_blaming_the_store(
        self, demo_backend_configured
    ):
        def select_nonsense(app):
            window = listed_window(app)
            window._on_password_selected(DEMO_BACKEND_ID, "no/such/entry")
            pump_until(lambda: window._placeholder_state == "failed")
            return window._placeholder_state, window.placeholder_page.get_description()

        state_name, description = run_in_application(select_nonsense)

        assert state_name == "failed"
        assert "no/such/entry" in description

    def test_a_store_with_no_entries_says_it_is_empty(self, monkeypatch):
        from gtkpass.backends.demo import DemoBackend

        monkeypatch.setattr(DemoBackend, "list_passwords", lambda self, prefix="": [])

        def state(app):
            return listed_window(app)._placeholder_state

        settings = get_settings()
        previous = settings.get_value("backend-instances")
        settings.set_value(
            "backend-instances", GLib.Variant("a(ss)", [(DEMO_BACKEND_ID, "demo")])
        )
        try:
            assert run_in_application(state) == "empty"
        finally:
            settings.set_value("backend-instances", previous)


class TestTheWindowOpensWhereItWasLeft:
    """Three schema keys existed from the start with nothing reading them.

    The window reset to its default size on every launch while dconf held a
    size somebody had chosen, which is worse than not offering the setting.
    """

    @pytest.fixture
    def stored_size(self):
        settings = get_settings()
        previous = (
            settings.get_int("window-width"),
            settings.get_int("window-height"),
        )
        settings.set_int("window-width", 1234)
        settings.set_int("window-height", 567)
        yield
        settings.set_int("window-width", previous[0])
        settings.set_int("window-height", previous[1])

    def test_the_stored_size_is_applied(self, stored_size):
        from gtkpass.window import GTKPassWindow

        size = run_in_application(
            lambda app: GTKPassWindow(application=app).get_default_size()
        )

        assert tuple(size) == (1234, 567)

    def test_a_resize_is_remembered(self, stored_size):
        from gtkpass.window import GTKPassWindow

        def resize(app):
            window = GTKPassWindow(application=app)
            window.set_default_size(800, 600)
            return get_settings().get_int("window-width")

        assert run_in_application(resize) == 800


class TestWindowWithDemoBackend:
    @pytest.fixture
    def rows(self, demo_backend_configured):
        def collect(app):
            return sidebar_names(listed_window(app))

        return run_in_application(collect)

    def test_backend_appears_in_the_sidebar(self, rows):
        assert "Demo" in rows

    def test_demo_passwords_are_listed(self, rows):
        """The demo backend ships sample entries; they must reach the tree."""
        assert len(rows) > 1, f"only the backend row was added: {rows}"

    def test_no_backend_is_marked_unavailable(self, rows):
        assert not [row for row in rows if "unavailable" in row]


class TestKeyboard:
    """Two accelerators for the whole application is not a keyboard interface.

    Ctrl+Q and Ctrl+, were the only ones, while the AppStream metadata claimed
    keyboard control. Every action the interface offers now has one, and a
    window documents them.
    """

    def test_every_window_action_an_accelerator_names_exists(
        self, demo_backend_configured
    ):
        """The bindings live on the application and the actions live here.

        A binding to an action that does not exist is a key that does nothing,
        and nothing else reports it: set_accels_for_action takes any name at
        all, including one nobody ever added.
        """
        from gtkpass.app import GTKPassApp

        wanted = sorted(
            name.removeprefix("win.")
            for name in GTKPassApp.ACCELS
            if name.startswith("win.")
        )

        def present(app):
            window = listed_window(app)
            return [name for name in wanted if window.lookup_action(name) is None]

        assert run_in_application(present) == []

    def test_the_shortcuts_window_is_installed(self, demo_backend_configured):
        """Without this, win.show-help-overlay does not exist to bind to."""

        def overlay(app):
            return listed_window(app).get_help_overlay()

        assert run_in_application(overlay) is not None

    def test_every_documented_shortcut_is_one_that_exists(
        self, demo_backend_configured
    ):
        """The window is written by hand, so it can drift from the bindings.

        A shortcuts window that lists an accelerator nothing is bound to is
        worse than no shortcuts window: it is a promise the application does
        not keep.
        """
        from gtkpass._gi import Gtk

        def documented(app):
            window = listed_window(app)

            def walk(widget):
                child = widget.get_first_child()
                while child is not None:
                    if isinstance(child, Gtk.ShortcutsShortcut):
                        yield child.get_property("accelerator")
                    yield from walk(child)
                    child = child.get_next_sibling()

            return list(walk(window.get_help_overlay()))

        from gtkpass.app import GTKPassApp

        listed = run_in_application(documented)

        assert listed, "the shortcuts window documents nothing at all"
        # Escape is not an accelerator: GtkSearchEntry emits stop-search for it
        # and the window clears the box, which is documented all the same.
        bound = {
            accelerator
            for accelerators in GTKPassApp.ACCELS.values()
            for accelerator in accelerators
        } | {"Escape"}
        assert set(listed) <= bound, f"documented but not bound: {set(listed) - bound}"

    def test_search_focuses_the_box(self, demo_backend_configured):
        def focused(window):
            """Whether the focus is on the search box or inside it.

            A GtkSearchEntry delegates its editing to a GtkText, and that is
            what actually takes the focus, so asking the entry itself answers
            False while the caret is blinking in it.
            """
            widget = window.get_focus()
            while widget is not None:
                if widget is window.search_entry:
                    return True
                widget = widget.get_parent()
            return False

        def focus(app):
            window = listed_window(app)
            window.present()
            try:
                pump_until(lambda: window.get_mapped())
                window.activate_action("win.search", None)
                pump_until(lambda: focused(window))
                return focused(window)
            finally:
                # A presented window keeps its application alive, and the next
                # test to run one under the same id becomes a remote instance
                # of it, which never activates.
                window.destroy()
                pump_until(lambda: not window.get_mapped())

        assert run_in_application(focus) is True

    def test_copying_the_password_needs_an_entry(self, demo_backend_configured):
        def enabled(app):
            return listed_window(app).lookup_action("copy-password").get_enabled()

        assert run_in_application(enabled) is False

    def test_copying_the_password_copies_the_one_on_display(
        self, demo_backend_configured
    ):
        copied = []

        def copy(app):
            window = listed_window(app)
            window._clipboard.copy = lambda value, timeout, secret=True: copied.append(
                value
            )
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            name = backend.list_passwords()[0].name
            window._on_password_selected(DEMO_BACKEND_ID, name)
            pump_until(
                lambda: window.password_detail.stack.get_visible_child_name()
                == "content"
            )
            expected = window.password_detail.password_row.get_text()

            window.activate_action("win.copy-password", None)
            return expected

        expected = run_in_application(copy)

        assert copied == [expected]

    def test_a_field_is_copied_before_the_pane_has_the_entry(
        self, demo_backend_configured
    ):
        """What the sidebar's context menu runs into.

        A right-click selects the row and puts the menu over it at once, so
        Copy Password can be chosen while the store is still decrypting.
        Reading the pane then would copy an empty string, or whatever the
        previous entry left in it, so the entry is fetched for the copy.
        """
        copied = []

        def copy(app):
            window = listed_window(app)
            window._clipboard.copy = lambda value, timeout, secret=True: copied.append(
                value
            )
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            wanted = backend.list_passwords()[0].name

            # Selected in the tree without going through the detail pane, as a
            # right-click does before its menu is even on screen.
            window.password_list.expand_all()
            names = [
                window.password_list.tree_model.get_row(index).get_item().password_name
                for index in range(window.password_list.tree_model.get_n_items())
            ]
            window.password_list.selection.set_selected(names.index(wanted))
            window._shown = None

            window.activate_action("win.copy-password", None)
            pump_until(lambda: bool(copied), timeout_seconds=5.0)
            return backend.get_password(wanted).password

        expected = run_in_application(copy)

        assert copied == [expected]

    def test_an_entry_with_no_username_says_so_rather_than_copying_nothing(
        self, demo_backend_configured
    ):
        from pathlib import Path

        from gtkpass.backends import PasswordEntry

        copied = []
        toasts: list[str] = []

        def copy(app):
            window = listed_window(app)
            window._clipboard.copy = lambda value, timeout, secret=True: copied.append(
                value
            )
            window._toast = toasts.append
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            name = backend.list_passwords()[0].name
            backend.get_password = lambda wanted: PasswordEntry(
                name=wanted, path=Path("demo://x"), content="s3cret\n"
            )
            window.password_list.expand_all()
            names = [
                window.password_list.tree_model.get_row(index).get_item().password_name
                for index in range(window.password_list.tree_model.get_n_items())
            ]
            window.password_list.selection.set_selected(names.index(name))
            window._shown = None

            window.activate_action("win.copy-username", None)
            pump_until(lambda: bool(toasts), timeout_seconds=5.0)

        run_in_application(copy)

        assert copied == []
        assert toasts and "no username" in toasts[0]


class TestNarrowWindows:
    """The metadata claimed 360 points and touch; the layout did neither.

    The split view was fixed open with no breakpoint and no way to put the
    sidebar away, so below about 650 points it squeezed the detail pane into
    nothing.
    """

    def at_width(self, app, width, settled, read):
        """Present a window ``width`` points wide and read something off it.

        Breakpoints apply during allocation, so the loop has to turn: asking
        straight after set_default_size reads the state the window had before
        it was that size.

        The window is destroyed again on the way out, and that is not tidiness.
        A presented window keeps its GApplication alive, and the next test to
        run one under the same application id becomes a remote instance of it
        -- which never activates, so the test after this one fails instead.
        """
        window = loaded_window(app)
        window.set_default_size(width, 600)
        window.present()
        try:
            pump_until(lambda: window.get_width() == width)
            pump_until(lambda: settled(window))
            return read(window)
        finally:
            window.destroy()
            pump_until(lambda: not window.get_mapped())

    def test_a_narrow_window_collapses_the_sidebar(self, demo_backend_configured):
        collapsed = run_in_application(
            lambda app: self.at_width(
                app,
                400,
                lambda window: window.split_view.get_collapsed(),
                lambda window: window.split_view.get_collapsed(),
            )
        )

        assert collapsed is True

    def test_a_narrow_window_offers_the_sidebar_button(self, demo_backend_configured):
        visible = run_in_application(
            lambda app: self.at_width(
                app,
                400,
                lambda window: window.sidebar_button.get_visible(),
                lambda window: window.sidebar_button.get_visible(),
            )
        )

        assert visible is True

    def test_a_wide_window_keeps_the_sidebar_in_place(self, demo_backend_configured):
        collapsed, button = run_in_application(
            lambda app: self.at_width(
                app,
                1000,
                lambda window: True,
                lambda window: (
                    window.split_view.get_collapsed(),
                    window.sidebar_button.get_visible(),
                ),
            )
        )

        assert collapsed is False
        assert button is False, "a button to show what is already shown"

    def test_the_button_follows_the_sidebar(self, demo_backend_configured):
        """Bidirectional, so it shows the state as well as setting it."""

        def toggled(app):
            window = loaded_window(app)
            window.split_view.set_show_sidebar(False)
            was_off = window.sidebar_button.get_active()
            window.sidebar_button.set_active(True)
            return was_off, window.split_view.get_show_sidebar()

        was_off, shown = run_in_application(toggled)

        assert was_off is False
        assert shown is True

    def test_choosing_an_entry_gets_the_sidebar_out_of_the_way(
        self, demo_backend_configured
    ):
        """Collapsed, the sidebar is an overlay over the pane being filled."""

        def select(app):
            window = listed_window(app)
            window.split_view.set_collapsed(True)
            window.split_view.set_show_sidebar(True)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            window._on_password_selected(
                DEMO_BACKEND_ID, backend.list_passwords()[0].name
            )
            return window.split_view.get_show_sidebar()

        assert run_in_application(select) is False

    def test_the_sidebar_stays_put_at_full_width(self, demo_backend_configured):
        def select(app):
            window = listed_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            window._on_password_selected(
                DEMO_BACKEND_ID, backend.list_passwords()[0].name
            )
            return window.split_view.get_show_sidebar()

        assert run_in_application(select) is True


class TestSearch:
    """The box sat in the sidebar with nothing behind it, and a preference
    switch offered control over a feature that did not exist. Typing in it did
    nothing at all.
    """

    @pytest.fixture
    def search_as_you_type(self):
        """Both settings, restored afterwards, because the default matters."""
        settings = get_settings()
        previous = settings.get_boolean("search-as-you-type")

        def set_to(value):
            settings.set_boolean("search-as-you-type", value)

        yield set_to
        settings.set_boolean("search-as-you-type", previous)

    def test_typing_narrows_the_sidebar(
        self, demo_backend_configured, search_as_you_type
    ):
        search_as_you_type(True)

        def search(app):
            window = listed_window(app)
            before = sidebar_names(window)
            window.search_entry.set_text("mail")
            # GtkSearchEntry holds search-changed back for a moment, so that a
            # search is not run per keystroke. Turning the loop is what a typing
            # user does by pausing.
            pump_until(lambda: sidebar_names(window) != before)
            return before, sidebar_names(window)

        before, after = run_in_application(search)

        assert len(after) < len(before)
        assert [name for name in after if "mail" in name.lower()]

    def test_clearing_the_box_brings_the_tree_back(
        self, demo_backend_configured, search_as_you_type
    ):
        search_as_you_type(True)

        def search(app):
            window = listed_window(app)
            before = sidebar_names(window)
            window.search_entry.set_text("mail")
            pump_until(lambda: sidebar_names(window) != before)
            window.search_entry.set_text("")
            pump_until(lambda: sidebar_names(window) == before)
            return before, sidebar_names(window)

        before, after = run_in_application(search)

        assert after == before

    def test_without_search_as_you_type_nothing_happens_until_enter(
        self, demo_backend_configured, search_as_you_type
    ):
        search_as_you_type(False)

        def search(app):
            window = listed_window(app)
            window.search_entry.set_text("mail")
            typed = sidebar_names(window)
            window.search_entry.emit("activate")
            return typed, sidebar_names(window)

        typed, entered = run_in_application(search)

        assert len(entered) < len(typed)

    def test_a_search_with_no_matches_says_so(
        self, demo_backend_configured, search_as_you_type
    ):
        """Distinct from an empty store, which is not the user's mistake."""
        search_as_you_type(True)

        def search(app):
            window = listed_window(app)
            window.search_entry.set_text("no such entry anywhere")
            pump_until(lambda: window._placeholder_state != "ready")
            return window._placeholder_state

        assert run_in_application(search) == "no-matches"

    def test_the_store_is_not_called_empty_because_a_search_matched_nothing(
        self, demo_backend_configured, search_as_you_type
    ):
        search_as_you_type(True)

        def search(app):
            window = listed_window(app)
            window.search_entry.set_text("no such entry anywhere")
            pump_until(lambda: window._placeholder_state == "no-matches")
            window.search_entry.set_text("")
            pump_until(lambda: window._placeholder_state != "no-matches")
            return window._placeholder_state

        assert run_in_application(search) == "ready"


class TestABackendThatWouldNotLoad:
    """It said so once, in a toast, for five seconds, and then never again.

    The sidebar row read "(unavailable)" and carried no reason, and there was
    no way to try again short of quitting -- though what stops a backend
    loading is almost always outside the application and fixed there: a store
    on a mount that was not up, a locked keyring, an agent that had not
    started.
    """

    @pytest.fixture
    def broken(self, demo_backend_configured, monkeypatch):
        from gtkpass.backends import BackendError
        from gtkpass.window import GTKPassWindow

        def refuse(self, backend_type, settings):
            raise BackendError("the store is not mounted")

        monkeypatch.setattr(GTKPassWindow, "_create_backend", refuse)

    def failed_window(self, app):
        from gtkpass.window import GTKPassWindow

        window = GTKPassWindow(application=app)
        assert pump_until(lambda: bool(window.failed_backends)), (
            "the backend never failed"
        )
        return window

    def test_the_row_carries_the_reason(self, broken):
        def tooltip(app):
            window = self.failed_window(app)
            pump_until(lambda: window.password_list.root.get_n_items() > 0)
            return window.password_list.root.get_item(0).tooltip

        assert "not mounted" in run_in_application(tooltip)

    def test_the_row_says_it_is_unavailable(self, broken):
        def name(app):
            window = self.failed_window(app)
            pump_until(lambda: window.password_list.root.get_n_items() > 0)
            return window.password_list.root.get_item(0).name

        assert "unavailable" in run_in_application(name)

    def test_the_toast_offers_a_retry(self, broken):
        from gtkpass._gi import Adw as _Adw

        toasts: list[_Adw.Toast] = []

        def report(app):
            window = self.failed_window(app)
            window.toast_overlay.add_toast = toasts.append
            window._show_backend_errors()

        run_in_application(report)

        assert toasts
        assert toasts[0].get_button_label() == "Retry"
        assert toasts[0].get_action_name() == "win.reload"

    def test_reloading_tries_the_backends_again(self, broken, monkeypatch):
        """The point of the retry: what failed before need not fail again."""

        def reload(app):
            window = self.failed_window(app)

            # Whatever was wrong is now put right, as it would be outside.
            monkeypatch.undo()
            window.activate_action("win.reload", None)

            assert pump_until(
                lambda: window.backend_manager.get_backend(DEMO_BACKEND_ID) is not None
            ), "the reload did not build the backend"
            return window.failed_backends

        assert run_in_application(reload) == []

    def test_reloading_is_always_offered(self, demo_backend_configured):
        """It is how somebody picks up a store that changed under the window."""

        def enabled(app):
            return listed_window(app).lookup_action("reload").get_enabled()

        assert run_in_application(enabled) is True


class TestTheTreeKeepsItsShapeAcrossAReListing:
    """Every write and every sync re-lists, and re-listing rebuilt the tree.

    Saving an entry three levels down and being returned to a shut tree, with
    the way back to it to be found again, is the same interruption whether it
    came from a save, an add, a delete or a sync.
    """

    def visible(self, window):
        model = window.password_list.tree_model
        return [
            model.get_row(index).get_item().name for index in range(model.get_n_items())
        ]

    def opened_window(self, app):
        """A listed window with every folder opened, as a user leaves it."""
        window = listed_window(app)
        window.password_list.expand_all()
        return window

    def test_a_reload_leaves_the_tree_as_it_was(self, demo_backend_configured):
        def reload(app):
            window = self.opened_window(app)
            before = self.visible(window)
            assert any("/" not in name for name in before)

            window._load_passwords()
            pump_until(lambda: window._pending_listings == 0)
            return before, self.visible(window)

        before, after = run_in_application(reload)

        assert after == before

    def test_a_folder_left_shut_stays_shut(self, demo_backend_configured):
        def reload(app):
            window = listed_window(app)
            before = self.visible(window)

            window._load_passwords()
            pump_until(lambda: window._pending_listings == 0)
            return before, self.visible(window)

        before, after = run_in_application(reload)

        assert after == before

    def test_a_sync_does_not_shut_the_tree(self, demo_backend_configured):
        def sync(app):
            window = self.opened_window(app)
            before = self.visible(window)

            # What _sync_finished does once the last backend has answered.
            window._sync_finished()
            pump_until(lambda: window._pending_listings == 0)
            return before, self.visible(window)

        before, after = run_in_application(sync)

        assert after == before


class TestLoadingStaysOffTheUiThread:
    """Nothing slow may happen between construction and a window on screen.

    Building a backend runs three git commands over its store, and the Secret
    Service one opens a D-Bus connection, waits up to five seconds for an answer
    and may unlock a collection. Listing walks the store's whole directory tree.
    All of it ran inside __init__, so the window did not appear until every
    configured backend had answered -- and a store on a mount that had gone away
    meant it never did.
    """

    #: Long enough that a window built while it runs cannot have waited for it.
    SLOW_SECONDS = 1.0

    def test_backends_are_not_built_on_the_ui_thread(
        self, demo_backend_configured, monkeypatch
    ):
        from gtkpass.window import GTKPassWindow

        threads: list[threading.Thread] = []
        original = GTKPassWindow._create_backend

        def record(self, backend_type, settings):
            threads.append(threading.current_thread())
            return original(self, backend_type, settings)

        monkeypatch.setattr(GTKPassWindow, "_create_backend", record)

        def check(app):
            loaded_window(app)
            return [thread is threading.main_thread() for thread in threads]

        on_main = run_in_application(check)

        assert on_main, "no backend was built at all, so this proves nothing"
        assert not any(on_main)

    def test_the_window_is_built_before_a_slow_backend_finishes(
        self, demo_backend_configured, monkeypatch
    ):
        from gtkpass.window import GTKPassWindow

        original = GTKPassWindow._create_backend

        # `self` here is the window, not the test, so the delay is named through
        # the class rather than through it.
        delay = self.SLOW_SECONDS

        def slow(self, backend_type, settings):
            time.sleep(delay)
            return original(self, backend_type, settings)

        monkeypatch.setattr(GTKPassWindow, "_create_backend", slow)

        def check(app):
            started = time.monotonic()
            window = GTKPassWindow(application=app)
            construction = time.monotonic() - started
            arrived = pump_until(
                lambda: window.backend_manager.get_backend(DEMO_BACKEND_ID) is not None
            )
            return construction, arrived

        construction, arrived = run_in_application(check)

        assert construction < self.SLOW_SECONDS, (
            "the constructor waited for the backend; that is a window that does "
            "not appear"
        )
        assert arrived, "the backend never turned up afterwards either"

    def test_listing_is_not_done_on_the_ui_thread(self, demo_backend_configured):
        def check(app):
            window = listed_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            assert backend is not None

            threads: list[threading.Thread] = []
            original = backend.list_passwords

            def record(prefix=""):
                threads.append(threading.current_thread())
                return original(prefix)

            backend.list_passwords = record  # type: ignore[method-assign]
            window._load_passwords()
            pump_until(lambda: bool(threads))
            return [thread is threading.main_thread() for thread in threads]

        on_main = run_in_application(check)

        assert on_main, "the backend was never asked for its entries"
        assert not any(on_main)


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

    def test_a_stored_name_is_shown(self, named_demo):
        names = run_in_application(lambda app: sidebar_names(listed_window(app)))

        assert "My Vault" in names

    def test_renaming_updates_an_open_window(self, demo_backend_configured):
        def rename_while_open(app):
            window = listed_window(app)
            assert "Demo" in sidebar_names(window)

            set_backend_display_name("demo", DEMO_BACKEND_ID, "Renamed Live")
            try:
                return sidebar_names(window)
            finally:
                set_backend_display_name("demo", DEMO_BACKEND_ID, "")

        assert "Renamed Live" in run_in_application(rename_while_open)


class TestShowingDetails:
    """Selecting an entry decrypts it and shows it in the detail pane."""

    def open_first_password(self, app):
        """Build a window and select the first demo entry, synchronously."""
        window = loaded_window(app)
        backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
        assert backend is not None
        name = backend.list_passwords()[0].name

        window._on_password_selected(DEMO_BACKEND_ID, name)
        pump_until(
            lambda: window.content_stack.get_visible_child_name() == "detail"
            and window.password_detail.stack.get_visible_child_name() == "content"
        )
        return window, name

    def test_the_detail_pane_is_shown(self, demo_backend_configured):
        window, _ = run_in_application(self.open_first_password)

        assert window.content_stack.get_visible_child_name() == "detail"

    def test_the_entry_is_decrypted_and_displayed(self, demo_backend_configured):
        window, name = run_in_application(self.open_first_password)

        assert displayed_name(window) == name
        assert window.password_detail.password_row.get_text()

    def test_a_missing_entry_reports_instead_of_crashing(self, demo_backend_configured):
        def select_nonsense(app):
            window = loaded_window(app)
            window._on_password_selected(DEMO_BACKEND_ID, "no/such/entry")
            pump_until(
                lambda: window.content_stack.get_visible_child_name() == "placeholder"
            )
            return window.content_stack.get_visible_child_name()

        assert run_in_application(select_nonsense) == "placeholder"

    def test_editing_is_not_offered_before_anything_is_open(
        self, demo_backend_configured
    ):
        from gtkpass.window import GTKPassWindow

        def edit_enabled(app):
            window = GTKPassWindow(application=app)
            return window.lookup_action("edit-password").get_enabled()

        assert run_in_application(edit_enabled) is False

    def test_editing_is_offered_for_an_open_entry(self, demo_backend_configured):
        window, _ = run_in_application(self.open_first_password)

        assert window.lookup_action("edit-password").get_enabled()


class TestTheRevealPreference:
    """'show hidden passwords' has to reach the pane that shows them.

    It used to be a Gio.Settings.bind onto a property Adw.PasswordEntryRow does
    not have: a GLib-GIO-CRITICAL on every window construction, and a setting
    that did nothing.
    """

    @pytest.fixture
    def reveal(self):
        settings = get_settings()
        previous = settings.get_boolean("show-hidden-passwords")
        settings.set_boolean("show-hidden-passwords", True)
        yield
        settings.set_boolean("show-hidden-passwords", previous)

    def revealed(self, window) -> bool:
        return window.password_detail.password_row.get_delegate().get_visibility()

    def test_an_opened_entry_honours_the_preference(
        self, demo_backend_configured, reveal
    ):
        window, _ = run_in_application(TestShowingDetails().open_first_password)

        assert self.revealed(window)

    def test_it_is_hidden_when_the_preference_is_off(self, demo_backend_configured):
        window, _ = run_in_application(TestShowingDetails().open_first_password)

        assert not self.revealed(window)

    def test_changing_the_preference_reaches_an_open_window(
        self, demo_backend_configured
    ):
        from gtkpass.window import GTKPassWindow

        def toggle_while_open(app):
            window = GTKPassWindow(application=app)
            settings = get_settings()
            previous = settings.get_boolean("show-hidden-passwords")
            settings.set_boolean("show-hidden-passwords", True)
            try:
                return self.revealed(window)
            finally:
                settings.set_boolean("show-hidden-passwords", previous)

        assert run_in_application(toggle_while_open)


class TestEditing:
    """Saving the edit dialog writes through the backend and re-reads it."""

    def open_and_save(self, app, new_password, backend_edit=None):
        """Open an entry, then drive its edit dialog to the Save button.

        Returns the entry name, whatever the backend was asked to write, and
        the toasts the window raised.
        """
        window = loaded_window(app)
        backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
        assert backend is not None
        if backend_edit is not None:
            backend.edit_password = backend_edit  # type: ignore[method-assign]

        toasts: list[str] = []
        window._toast = toasts.append  # type: ignore[method-assign,assignment]

        name = backend.list_passwords()[0].name
        window._on_password_selected(DEMO_BACKEND_ID, name)
        pump_until(
            lambda: window.password_detail.stack.get_visible_child_name() == "content"
        )

        dialog = window._open_edit_dialog()
        assert dialog is not None, "the edit dialog did not open"
        dialog.password_row.set_text(new_password)
        dialog.save_button.emit("clicked")
        pump_until(lambda: bool(toasts), timeout_seconds=5.0)
        return name, toasts

    def test_the_backend_is_asked_to_write_the_new_content(
        self, demo_backend_configured
    ):
        written = []

        def record(name, content, commit=True):
            written.append((name, content))

        name, _ = run_in_application(
            lambda app: self.open_and_save(app, "replaced", backend_edit=record)
        )

        assert [entry[0] for entry in written] == [name]
        assert written[0][1].startswith("replaced\n")

    def test_a_successful_write_is_confirmed(self, demo_backend_configured):
        def record(name, content, commit=True):
            pass

        _, toasts = run_in_application(
            lambda app: self.open_and_save(app, "replaced", backend_edit=record)
        )

        assert toasts and "aved" in toasts[0]

    def test_a_refused_write_is_reported_and_not_swallowed(
        self, demo_backend_configured
    ):
        """The demo backend is read-only, so refusal is its real behaviour."""
        _, toasts = run_in_application(lambda app: self.open_and_save(app, "replaced"))

        assert toasts and "read-only" in toasts[0]

    def test_a_stale_decrypt_cannot_overwrite_a_newer_selection(
        self, demo_backend_configured
    ):
        """Arrow-keying through the tree starts one decrypt per row.

        A slow one landing after a later selection must be discarded, or the
        pane shows an entry the user has already moved off. The two futures are
        resolved out of order here to force exactly that.
        """
        from concurrent.futures import Future

        def select_twice(app):
            window = loaded_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            assert backend is not None
            first, second = (p.name for p in backend.list_passwords()[:2])

            pending: list[tuple[str, Future]] = []

            def capture(_backend_id, name):
                pending.append((name, Future()))
                return pending[-1][1]

            # Hold both decrypts open so they can be resolved out of order.
            window.backend_manager.get_password_async = capture  # type: ignore[assignment]

            window._on_password_selected(DEMO_BACKEND_ID, first)
            window._on_password_selected(DEMO_BACKEND_ID, second)

            # Newer first, then the stale one arrives late.
            for name, future in reversed(pending):
                future.set_result(backend.get_password(name))

            pump_until(lambda: False, timeout_seconds=0.5)
            return displayed_name(window), second

        shown, expected = run_in_application(select_twice)
        assert shown == expected


class TestAdding:
    """The `+` button opened a "Not Implemented Yet" dialog for as long as
    there had been a `+` button, while every backend that can write had
    implemented add_password all along.
    """

    def writable_window(self, app):
        """A loaded window whose demo backend will accept a write.

        The demo store is read-only on purpose, so nothing offers to add to it.
        Making this one writable is what lets the flow above it be exercised
        without a GPG store and a key.
        """
        window = listed_window(app)
        backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
        backend.writable = True
        window._refresh_write_actions()
        return window

    def test_a_read_only_store_is_not_offered_the_dialog(self, demo_backend_configured):
        def enabled(app):
            window = listed_window(app)
            return window.lookup_action("add-password").get_enabled()

        assert run_in_application(enabled) is False

    def test_the_reason_is_in_the_tooltip(self, demo_backend_configured):
        def tooltip(app):
            return listed_window(app).add_button.get_tooltip_text()

        assert "read-only" in run_in_application(tooltip)

    def test_a_writable_store_is_offered_the_dialog(self, demo_backend_configured):
        def enabled(app):
            window = self.writable_window(app)
            return window.lookup_action("add-password").get_enabled()

        assert run_in_application(enabled) is True

    def test_saving_asks_the_backend_to_write_it(self, demo_backend_configured):
        written = []

        def add(app):
            window = self.writable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            backend.add_password = lambda name, content, commit=True: written.append(
                (name, content)
            )

            dialog = window._open_add_dialog()
            assert dialog is not None, "the add dialog did not open"
            dialog.name_row.set_text("new/entry")
            dialog.password_row.set_text("s3cret")
            dialog.save_button.emit("clicked")
            pump_until(lambda: bool(written), timeout_seconds=5.0)

        run_in_application(add)

        assert written == [("new/entry", "s3cret\n")]

    def test_the_name_is_tidied_rather_than_taken_literally(
        self, demo_backend_configured
    ):
        """A stray slash is a typo, not a folder with no name."""
        written = []

        def add(app):
            window = self.writable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            backend.add_password = lambda name, content, commit=True: written.append(
                name
            )

            dialog = window._open_add_dialog()
            dialog.name_row.set_text("/work//mail/")
            dialog.password_row.set_text("s3cret")
            dialog.save_button.emit("clicked")
            pump_until(lambda: bool(written), timeout_seconds=5.0)

        run_in_application(add)

        assert written == ["work/mail"]

    def test_an_entry_with_no_name_is_not_written(self, demo_backend_configured):
        written = []

        def add(app):
            window = self.writable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            backend.add_password = lambda *args, **kwargs: written.append(args)

            dialog = window._open_add_dialog()
            dialog.password_row.set_text("s3cret")
            dialog.save_button.emit("clicked")
            return dialog

        dialog = run_in_application(add)

        assert written == []
        assert dialog.get_child() is not None, "the dialog closed on a refusal"

    def test_an_entry_with_no_password_is_not_written(self, demo_backend_configured):
        written = []

        def add(app):
            window = self.writable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            backend.add_password = lambda *args, **kwargs: written.append(args)

            dialog = window._open_add_dialog()
            dialog.name_row.set_text("new/entry")
            dialog.save_button.emit("clicked")

        run_in_application(add)

        assert written == []

    def test_a_name_already_in_the_store_is_refused(self, demo_backend_configured):
        """Before the write, rather than as a FileExistsError after it."""
        written = []

        def add(app):
            window = self.writable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            existing = backend.list_passwords()[0].name
            backend.add_password = lambda *args, **kwargs: written.append(args)

            dialog = window._open_add_dialog()
            dialog.name_row.set_text(existing)
            dialog.password_row.set_text("s3cret")
            dialog.save_button.emit("clicked")
            return dialog.name_row.has_css_class("error")

        marked = run_in_application(add)

        assert written == []
        assert marked, "nothing on the row said why the save did nothing"

    def test_a_failed_write_is_reported(self, demo_backend_configured):
        from gtkpass.backends import BackendError

        def add(app):
            window = self.writable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)

            def refuse(name, content, commit=True):
                raise BackendError("the store is on fire")

            backend.add_password = refuse
            toasts: list[str] = []
            window._toast = toasts.append

            dialog = window._open_add_dialog()
            dialog.name_row.set_text("new/entry")
            dialog.password_row.set_text("s3cret")
            dialog.save_button.emit("clicked")
            pump_until(lambda: bool(toasts), timeout_seconds=5.0)
            return toasts

        toasts = run_in_application(add)

        assert toasts and "the store is on fire" in toasts[0]

    def test_the_dialog_starts_in_the_folder_the_user_was_in(
        self, demo_backend_configured
    ):
        def prefilled(app):
            window = self.writable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            nested = next(
                entry.name for entry in backend.list_passwords() if "/" in entry.name
            )
            window.password_list.expand_all()
            names = [
                window.password_list.tree_model.get_row(index).get_item().password_name
                for index in range(window.password_list.tree_model.get_n_items())
            ]
            window.password_list.selection.set_selected(names.index(nested))

            dialog = window._open_add_dialog()
            return nested.rpartition("/")[0], dialog.name_row.get_text()

        folder, prefilled_name = run_in_application(prefilled)

        assert prefilled_name == f"{folder}/"

    def test_generating_fills_the_password_in(self, demo_backend_configured):
        def generate(app):
            window = self.writable_window(app)
            dialog = window._open_add_dialog()
            dialog.length_row.set_value(24)
            dialog.generate_button.emit("clicked")
            return dialog.password_row.get_text()

        generated = run_in_application(generate)

        assert len(generated) == 24

    def test_a_generated_password_is_shown_rather_than_dotted_out(
        self, demo_backend_configured
    ):
        """Somebody who has just generated one has not seen it yet."""

        def generate(app):
            window = self.writable_window(app)
            dialog = window._open_add_dialog()
            dialog.generate_button.emit("clicked")
            return dialog.password_row.get_delegate().get_visibility()

        assert run_in_application(generate) is True


class TestDeleting:
    """Deleting asks first, and asks about a named entry.

    What GTKPass writes to a store it can commit, but it cannot bring back a
    secret nobody else has a copy of, so this is the one operation that stops
    to ask.
    """

    def deletable_window(self, app):
        window = listed_window(app)
        backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
        backend.writable = True
        window._refresh_write_actions()
        return window

    def open_entry(self, window):
        backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
        name = backend.list_passwords()[0].name
        window._on_password_selected(DEMO_BACKEND_ID, name)
        pump_until(
            lambda: window.password_detail.stack.get_visible_child_name() == "content"
        )
        return name

    def test_nothing_is_offered_before_an_entry_is_open(self, demo_backend_configured):
        def enabled(app):
            return self.deletable_window(app).lookup_action("delete-password")

        assert run_in_application(enabled).get_enabled() is False

    def test_an_open_entry_can_be_deleted(self, demo_backend_configured):
        def enabled(app):
            window = self.deletable_window(app)
            self.open_entry(window)
            return window.lookup_action("delete-password").get_enabled()

        assert run_in_application(enabled) is True

    def test_a_read_only_store_offers_nothing(self, demo_backend_configured):
        def enabled(app):
            window = listed_window(app)
            self.open_entry(window)
            return window.lookup_action("delete-password").get_enabled()

        assert run_in_application(enabled) is False

    def test_the_entry_is_named_in_the_question(self, demo_backend_configured):
        def ask(app):
            window = self.deletable_window(app)
            name = self.open_entry(window)
            dialog = window._confirm_delete()
            return name, dialog.get_body()

        name, body = run_in_application(ask)

        assert name in body

    def test_cancelling_deletes_nothing(self, demo_backend_configured):
        deleted = []

        def ask(app):
            window = self.deletable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            backend.delete_password = lambda name, commit=True: deleted.append(name)
            self.open_entry(window)

            window._confirm_delete().emit("response", "cancel")
            pump_until(lambda: False, timeout_seconds=0.2)

        run_in_application(ask)

        assert deleted == []

    def test_confirming_asks_the_backend_to_delete_it(self, demo_backend_configured):
        deleted = []

        def ask(app):
            window = self.deletable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            backend.delete_password = lambda name, commit=True: deleted.append(name)
            name = self.open_entry(window)

            window._confirm_delete().emit("response", "delete")
            pump_until(lambda: bool(deleted), timeout_seconds=5.0)
            return name

        name = run_in_application(ask)

        assert deleted == [name]

    def test_the_pane_lets_go_of_the_deleted_entry(self, demo_backend_configured):
        def ask(app):
            window = self.deletable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            backend.delete_password = lambda name, commit=True: None
            self.open_entry(window)

            window._confirm_delete().emit("response", "delete")
            pump_until(lambda: window._shown is None, timeout_seconds=5.0)
            return window._shown, window.content_stack.get_visible_child_name()

        shown, page = run_in_application(ask)

        assert shown is None
        assert page == "placeholder"

    def test_a_failed_delete_is_reported(self, demo_backend_configured):
        from gtkpass.backends import BackendError

        def ask(app):
            window = self.deletable_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)

            def refuse(name, commit=True):
                raise BackendError("the store is read-only after all")

            backend.delete_password = refuse
            toasts: list[str] = []
            window._toast = toasts.append
            self.open_entry(window)

            window._confirm_delete().emit("response", "delete")
            pump_until(lambda: bool(toasts), timeout_seconds=5.0)
            return toasts

        toasts = run_in_application(ask)

        assert toasts and "read-only after all" in toasts[0]


class TestACopiedSecretIsTakenBack:
    """A copy is kept for as long as there is a reason to keep it.

    The timeout is the outer bound. Moving to another entry ends the reason
    sooner, and closing the window ends it altogether.
    """

    def copy_from_first_entry(self, app):
        """A window with a password copied out of the entry on display."""
        window, name = TestShowingDetails().open_first_password(app)
        cleared: list[str] = []
        window._clipboard.clear_if_ours = lambda: cleared.append(  # type: ignore[method-assign]
            "taken back"
        )
        window._on_copy_requested(None, "Password", "hunter2")
        return window, name, cleared

    def test_opening_another_entry_takes_it_back(self, demo_backend_configured):
        def check(app):
            window, name, cleared = self.copy_from_first_entry(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            assert backend is not None
            other = next(p.name for p in backend.list_passwords() if p.name != name)

            window._on_password_selected(DEMO_BACKEND_ID, other)
            pump_until(lambda: bool(cleared))
            return cleared

        assert run_in_application(check) == ["taken back"]

    def test_re_opening_the_same_entry_does_not(self, demo_backend_configured):
        """Saving an edit re-selects the entry; that is not moving off it."""

        def check(app):
            window, name, cleared = self.copy_from_first_entry(app)

            window._on_password_selected(DEMO_BACKEND_ID, name)
            pump_until(lambda: bool(cleared), timeout_seconds=1.0)
            return cleared

        assert run_in_application(check) == []

    def test_the_window_can_be_told_to_give_it_up(self, demo_backend_configured):
        """What GTKPassApp.do_shutdown calls; see test_app.py for the hook."""

        def check(app):
            window = loaded_window(app)
            emptied: list[str] = []
            window._clipboard.clear_at_shutdown = lambda: emptied.append(  # type: ignore[method-assign]
                "emptied"
            )

            window.discard_clipboard()
            return emptied

        assert run_in_application(check) == ["emptied"]


class TestEntryNamesStayOutOfTheLog:
    """An entry name says which accounts somebody holds.

    Logging goes to stderr, which the journal collects when the application is
    launched from its desktop file -- and --debug is exactly the flag somebody
    turns on when something is wrong, which is the worst moment to start writing
    the names down. The toast carries the name, on screen, where it belongs.
    """

    def test_opening_an_entry_does_not_write_its_name_down(
        self, demo_backend_configured, caplog
    ):
        def check(app):
            window = loaded_window(app)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            assert backend is not None
            name = backend.list_passwords()[0].name

            with caplog.at_level(logging.DEBUG):
                window._on_password_selected(DEMO_BACKEND_ID, name)
                pump_until(
                    lambda: window.password_detail.stack.get_visible_child_name()
                    == "content"
                )
            return name, caplog.text

        name, logged = run_in_application(check)

        assert name not in logged
        assert DEMO_BACKEND_ID in logged, "the backend is still identified"


class TestRecipientsThatChanged:
    """A store whose readership changed says so until somebody has looked.

    The backend refuses to write to it; the banner is what makes that visible
    before anyone runs into the refusal, and carries the only way to lift it.
    """

    def audit(self, changed=True, stale=("email/work",)):
        from gtkpass.backends.recipients import RecipientAudit

        return RecipientAudit(
            record=". someone@example.invalid",
            changed=changed,
            added=("someone@example.invalid",),
            stale_entries=stale,
        )

    def window_reporting(self, app, audit):
        window = loaded_window(app)
        backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
        assert backend is not None
        backend.recipient_audit = lambda: audit  # type: ignore[method-assign]
        window._refresh_recipient_banner()
        return window

    def test_the_banner_is_shown(self, demo_backend_configured):
        revealed = run_in_application(
            lambda app: self.window_reporting(app, self.audit()).recipient_banner
        ).get_revealed()

        assert revealed

    def test_it_is_not_shown_for_a_store_nobody_touched(self, demo_backend_configured):
        revealed = run_in_application(
            lambda app: self.window_reporting(
                app, self.audit(changed=False)
            ).recipient_banner
        ).get_revealed()

        assert not revealed

    def test_the_banner_names_the_backend(self, demo_backend_configured):
        title = run_in_application(
            lambda app: self.window_reporting(app, self.audit()).recipient_banner
        ).get_title()

        assert "Demo" in title

    def test_the_review_dialog_can_be_built_and_accepted(self, demo_backend_configured):
        """Drives the real .ui, so a mistyped object id fails here.

        The instance is called a pass backend for the write: the record is kept
        in the per-instance schema, and only the two backends with a store have
        that key. What is under test is the dialog, not which backend it came
        from.
        """
        from gtkpass.config import get_backend_settings

        def check(app):
            window = loaded_window(app, backend_id=DEMO_BACKEND_ID)
            backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
            assert backend is not None
            audit = self.audit()
            backend.recipient_audit = lambda: audit  # type: ignore[method-assign]
            window.backend_types[DEMO_BACKEND_ID] = "pass"
            window._refresh_recipient_banner()

            dialog = window._open_recipients_dialog()
            assert dialog is not None, "the review dialog did not open"
            dialog.emit("response", "accept")

            return get_backend_settings("pass", DEMO_BACKEND_ID).get_string(
                "approved-recipients"
            )

        assert run_in_application(check) == ". someone@example.invalid"

    def test_accepting_records_the_set_and_lifts_the_refusal(self):
        """Recorded outside the store, where a remote cannot reach it.

        Written against the pass schema because that is one of the two that has
        the key; the demo backend has no store and so no recipients.
        """
        from gtkpass.config import get_backend_settings
        from gtkpass.window import GTKPassWindow

        backend_id = "pass_1766234611"

        def check(app):
            window = GTKPassWindow(application=app)
            window.backend_types[backend_id] = "pass"

            window._approve_recipients(backend_id, ". someone@example.invalid")

            return get_backend_settings("pass", backend_id).get_string(
                "approved-recipients"
            )

        assert run_in_application(check) == ". someone@example.invalid"


class TestSyncing:
    """The sync action, from the button through to a toast.

    The backend is stubbed with a Future held open by the test, the way the
    stale-decrypt test above does, so nothing here touches a network or a real
    repository.
    """

    def window_with_sync(self, app, capability, sync=None):
        """A window whose demo backend claims the given sync capability."""
        window = loaded_window(app)
        backend = window.backend_manager.get_backend(DEMO_BACKEND_ID)
        assert backend is not None
        backend.sync_capability = lambda: capability  # type: ignore[method-assign]
        if sync is not None:
            backend.sync = sync  # type: ignore[method-assign]
        window._refresh_sync_action()
        return window

    def test_it_is_not_offered_without_a_syncable_backend(
        self, demo_backend_configured
    ):
        from gtkpass.backends import SyncCapability, SyncUnavailable

        def check(app):
            window = self.window_with_sync(
                app,
                SyncCapability.unsupported(
                    SyncUnavailable.NO_REMOTE, "No remote is configured."
                ),
            )
            return (
                window.lookup_action("sync").get_enabled(),
                window.sync_button.get_tooltip_text(),
            )

        enabled, tooltip = run_in_application(check)

        assert not enabled
        assert tooltip == "No remote is configured."

    def test_it_is_offered_when_a_store_has_a_remote(self, demo_backend_configured):
        from gtkpass.backends import SyncCapability, SyncUnavailable

        def check(app):
            window = self.window_with_sync(
                app,
                SyncCapability(
                    supported=True,
                    reason=SyncUnavailable.READY,
                    detail="Sync with origin/main",
                    remote="origin",
                    branch="main",
                ),
            )
            return (
                window.lookup_action("sync").get_enabled(),
                window.sync_button.get_tooltip_text(),
            )

        enabled, tooltip = run_in_application(check)

        assert enabled
        assert tooltip == "Sync with origin/main"

    def ready(self):
        from gtkpass.backends import SyncCapability, SyncUnavailable

        return SyncCapability(
            supported=True,
            reason=SyncUnavailable.READY,
            detail="Sync with origin/main",
            remote="origin",
            branch="main",
        )

    def test_a_successful_sync_is_confirmed(self, demo_backend_configured):
        from gtkpass.backends import SyncResult

        def check(app):
            window = self.window_with_sync(
                app, self.ready(), sync=lambda: SyncResult(pulled=2, pushed=1)
            )
            toasts: list[str] = []
            window._toast = toasts.append  # type: ignore[method-assign,assignment]

            window.lookup_action("sync").activate(None)
            pump_until(lambda: bool(toasts), timeout_seconds=5.0)
            return toasts

        toasts = run_in_application(check)

        assert toasts, "the sync reported nothing"
        assert "2 in, 1 out" in toasts[0]

    def test_a_sync_that_moved_nothing_says_so(self, demo_backend_configured):
        from gtkpass.backends import SyncResult

        def check(app):
            window = self.window_with_sync(
                app, self.ready(), sync=lambda: SyncResult(pulled=0, pushed=0)
            )
            toasts: list[str] = []
            window._toast = toasts.append  # type: ignore[method-assign,assignment]

            window.lookup_action("sync").activate(None)
            pump_until(lambda: bool(toasts), timeout_seconds=5.0)
            return toasts

        toasts = run_in_application(check)

        assert toasts and "up to date" in toasts[0]

    def test_a_failure_is_reported_and_not_swallowed(self, demo_backend_configured):
        from gtkpass.backends import GitError

        def failing():
            raise GitError("git push failed: Permission denied (publickey)")

        def check(app):
            window = self.window_with_sync(app, self.ready(), sync=failing)
            toasts: list[str] = []
            window._toast = toasts.append  # type: ignore[method-assign,assignment]

            window.lookup_action("sync").activate(None)
            pump_until(lambda: bool(toasts), timeout_seconds=5.0)
            return toasts

        toasts = run_in_application(check)

        assert toasts, "a failed sync said nothing at all"
        assert "Permission denied" in toasts[0]

    def test_the_button_shows_progress_while_it_runs(self, demo_backend_configured):
        from concurrent.futures import Future

        def check(app):
            window = self.window_with_sync(app, self.ready())
            held: list[Future] = []

            def capture(_backend_id):
                held.append(Future())
                return held[-1]

            window.backend_manager.sync_async = capture  # type: ignore[assignment]
            window.lookup_action("sync").activate(None)

            busy = window.sync_stack.get_visible_child_name()
            enabled_while_busy = window.lookup_action("sync").get_enabled()
            return busy, enabled_while_busy

        busy, enabled_while_busy = run_in_application(check)

        assert busy == "busy"
        assert not enabled_while_busy, "a second sync could be started mid-sync"

    def test_the_button_goes_back_to_idle_afterwards(self, demo_backend_configured):
        from gtkpass.backends import SyncResult

        def check(app):
            window = self.window_with_sync(
                app, self.ready(), sync=lambda: SyncResult(pulled=0, pushed=0)
            )
            window.lookup_action("sync").activate(None)
            pump_until(
                lambda: window.sync_stack.get_visible_child_name() == "idle",
                timeout_seconds=5.0,
            )
            return window.sync_stack.get_visible_child_name()

        assert run_in_application(check) == "idle"

    def test_a_missing_permission_offers_the_override_command(
        self, demo_backend_configured
    ):
        """The whole point of not requesting ssh-auth up front."""
        from gtkpass.backends import SyncNotPermitted

        command = "flatpak override --user --socket=ssh-auth --share=network app.id"

        def blocked():
            raise SyncNotPermitted("Not permitted", command)

        def check(app):
            window = self.window_with_sync(app, self.ready(), sync=blocked)
            shown: list[str] = []
            window._show_sync_blocked = lambda error: shown.append(  # type: ignore[method-assign]
                error.override_command
            )

            window.lookup_action("sync").activate(None)
            pump_until(lambda: bool(shown), timeout_seconds=5.0)
            return shown

        shown = run_in_application(check)

        assert shown == [command]
