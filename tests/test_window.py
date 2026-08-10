"""End-to-end checks for the main window.

These cover the path a user actually takes: configure a backend, expect to see
its passwords.  That path was silently broken for months because nothing
exercised it.
"""

import threading
import time

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
