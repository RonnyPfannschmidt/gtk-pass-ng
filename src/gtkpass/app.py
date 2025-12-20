"""Main GTKPass application class."""

import sys
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402


class GTKPassApp(Adw.Application):
    """Main application class for GTKPass."""

    def __init__(self, **kwargs):
        """Initialize the application."""
        super().__init__(
            application_id="io.github.ronnypfannschmidt.GTKPass",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
            **kwargs,
        )
        self.window: Optional[Gtk.ApplicationWindow] = None

    def do_activate(self):
        """Activate the application."""
        # Import here to avoid circular imports
        from gtkpass.window import GTKPassWindow

        if not self.window:
            self.window = GTKPassWindow(application=self)
        self.window.present()

    def do_startup(self):
        """Initialize application on startup."""
        Adw.Application.do_startup(self)
        self._setup_actions()

    def _setup_actions(self):
        """Set up application actions."""
        # Quit action
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

        # Preferences action
        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self._on_preferences_action)
        self.add_action(preferences_action)
        self.set_accels_for_action("app.preferences", ["<Control>comma"])

        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about_action)
        self.add_action(about_action)

    def _on_preferences_action(self, action: Gio.SimpleAction, param):
        """Show the preferences window."""
        from gtkpass.ui.settings import SettingsWindow
        
        settings_window = SettingsWindow(transient_for=self.window)
        settings_window.present()

    def _on_about_action(self, action: Gio.SimpleAction, param):
        """Show the about dialog."""
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name="GTKPass",
            application_icon="io.github.ronnypfannschmidt.GTKPass",
            developer_name="GTKPass Contributors",
            version="0.0.1",
            website="https://github.com/RonnyPfannschmidt/gtkpass",
            issue_url="https://github.com/RonnyPfannschmidt/gtkpass/issues",
            license_type=Gtk.License.GPL_3_0,
            copyright="© 2024 GTKPass Contributors",
        )
        about.present()


def main():
    """Run the application."""
    app = GTKPassApp()
    return app.run(sys.argv)
