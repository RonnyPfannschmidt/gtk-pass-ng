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


class TestAccelerators:
    """Two of them was the whole keyboard interface, while the AppStream
    metadata claimed keyboard control. They are declared in one table now, and
    registered from it.
    """

    def registered(self):
        """The accelerators a started application actually holds."""
        from gtkpass.app import GTKPassApp

        app = GTKPassApp()
        held = {}

        def on_activate(_app):
            for action_name in GTKPassApp.ACCELS:
                held[action_name] = app.get_accels_for_action(action_name)
            app.quit()

        # do_activate would build a window and load backends; the actions are
        # registered in do_startup, which has run by the time this fires.
        app.connect("activate", on_activate)
        app.run([])
        return held

    def normalised(self, accelerator):
        """GTK's own spelling of an accelerator.

        It reorders the modifiers -- ``<Control><Shift>c`` comes back as
        ``<Shift><Control>c`` -- so comparing the strings as written would fail
        on nothing at all.
        """
        from gtkpass._gi import Gtk

        _ok, key, modifiers = Gtk.accelerator_parse(accelerator)
        return Gtk.accelerator_name(key, modifiers)

    def test_every_declared_accelerator_is_registered(self):
        from gtkpass.app import GTKPassApp

        held = self.registered()

        assert held == {
            name: [self.normalised(accelerator) for accelerator in accelerators]
            for name, accelerators in GTKPassApp.ACCELS.items()
        }

    def test_every_accelerator_is_spelled_in_a_way_gtk_understands(self):
        """A typo here is a shortcut that silently never fires."""
        from gtkpass._gi import Gtk
        from gtkpass.app import GTKPassApp

        for accelerators in GTKPassApp.ACCELS.values():
            for accelerator in accelerators:
                ok, key, _modifiers = Gtk.accelerator_parse(accelerator)
                assert ok and key, f"GTK does not understand {accelerator!r}"

    def test_no_accelerator_is_bound_to_two_actions(self):
        """Whichever action won would do so silently, and by declaration order."""
        from gtkpass.app import GTKPassApp

        seen: dict[str, str] = {}
        for name, accelerators in GTKPassApp.ACCELS.items():
            for accelerator in accelerators:
                spelling = self.normalised(accelerator)
                assert spelling not in seen, (
                    f"{accelerator} is bound to both {seen.get(spelling)} and {name}"
                )
                seen[spelling] = name


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
