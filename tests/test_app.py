"""Tests for the application object."""

import pytest

pytestmark = pytest.mark.gui


class TestGTKPassApp:
    def test_can_be_constructed(self):
        """Constructing the app must not create a window yet."""
        from gtkpass.app import GTKPassApp

        app = GTKPassApp()

        assert app.window is None


class TestQuittingTakesTheClipboardWithIt:
    """A copied password must not outlive the application.

    The clear is a GLib timeout, and a timeout cannot fire in a process that has
    exited -- so quitting inside the clipboard timeout used to leave the password
    on the clipboard for good. Hooked here rather than on the window: closing the
    last window and Ctrl+Q both arrive at shutdown, while "destroy" is emitted on
    dispose and this window outlives its own destruction whenever a settings
    handler or a pool callback still refers to it.
    """

    def test_shutdown_discards_it(self, monkeypatch):
        from gtkpass.app import GTKPassApp

        discarded: list[str] = []

        class FakeWindow:
            def discard_clipboard(self):
                discarded.append("discarded")

        app = GTKPassApp()
        app.window = FakeWindow()  # type: ignore[assignment]

        def on_activate(_app):
            app.quit()

        app.connect("activate", on_activate)
        app.run([])

        assert discarded == ["discarded"]
