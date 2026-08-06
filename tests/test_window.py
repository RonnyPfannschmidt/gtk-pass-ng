"""End-to-end checks for the main window.

These cover the path a user actually takes: configure a backend, expect to see
its passwords.  That path was silently broken for months because nothing
exercised it.
"""

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


def sidebar_names(window):
    """Every name in the sidebar tree, depth first."""

    def walk(store):
        for index in range(store.get_n_items()):
            node = store.get_item(index)
            yield node.name
            yield from walk(node.children)

    return list(walk(window.password_list.root))


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
            return sidebar_names(GTKPassWindow(application=app))

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

    def test_a_stored_name_is_shown(self, named_demo):
        from gtkpass.window import GTKPassWindow

        names = run_in_application(
            lambda app: sidebar_names(GTKPassWindow(application=app))
        )

        assert "My Vault" in names

    def test_renaming_updates_an_open_window(self, demo_backend_configured):
        from gtkpass.window import GTKPassWindow

        def rename_while_open(app):
            window = GTKPassWindow(application=app)
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
        from gtkpass.window import GTKPassWindow

        window = GTKPassWindow(application=app)
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

        assert window.password_detail.name_row.get_subtitle() == name
        assert window.password_detail.password_row.get_text()

    def test_a_missing_entry_reports_instead_of_crashing(self, demo_backend_configured):
        from gtkpass.window import GTKPassWindow

        def select_nonsense(app):
            window = GTKPassWindow(application=app)
            window._on_password_selected(DEMO_BACKEND_ID, "no/such/entry")
            pump_until(
                lambda: window.content_stack.get_visible_child_name() == "placeholder"
            )
            return window.content_stack.get_visible_child_name()

        assert run_in_application(select_nonsense) == "placeholder"

    def test_a_stale_decrypt_cannot_overwrite_a_newer_selection(
        self, demo_backend_configured
    ):
        """Arrow-keying through the tree starts one decrypt per row.

        A slow one landing after a later selection must be discarded, or the
        pane shows an entry the user has already moved off. The two futures are
        resolved out of order here to force exactly that.
        """
        from concurrent.futures import Future

        from gtkpass.window import GTKPassWindow

        def select_twice(app):
            window = GTKPassWindow(application=app)
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
            return window.password_detail.name_row.get_subtitle(), second

        shown, expected = run_in_application(select_twice)
        assert shown == expected
