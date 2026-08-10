"""Tests for the application object."""

import logging

import pytest

from gtkpass._gi import GLib

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


class TestTheLogLevelOption:
    """`--log-level` looked its argument up on the logging module.

    Any attribute name was accepted, so --log-level=basicConfig passed a
    function where a level was expected and the application died on startup --
    from the option that exists to find out why something is not working.
    """

    def options(self, level):
        options = GLib.VariantDict.new()
        options.insert_value("log-level", GLib.Variant("s", level))
        return options

    def test_a_known_level_is_accepted(self):
        from gtkpass.app import GTKPassApp

        assert GTKPassApp().do_handle_local_options(self.options("warning")) == -1

    def test_an_unknown_level_does_not_stop_the_application(self, caplog):
        from gtkpass.app import GTKPassApp

        with caplog.at_level(logging.WARNING):
            result = GTKPassApp().do_handle_local_options(self.options("basicConfig"))

        assert result == -1
        assert "Unknown log level" in caplog.text
