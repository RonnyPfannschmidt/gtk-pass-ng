"""Main GTKPass application class."""

import logging
import sys

from gtkpass._gi import Adw, Gio, GLib, Gtk
from gtkpass.config import APP_ID

# Setup logging
logger = logging.getLogger(__name__)


class GTKPassApp(Adw.Application):
    """Main application class for GTKPass."""

    def __init__(self, **kwargs):
        """Initialize the application."""
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
            **kwargs,
        )
        self.window: Gtk.ApplicationWindow | None = None

        # Add command-line options
        self.add_main_option(
            "debug",
            ord("d"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Enable debug logging",
            None,
        )
        self.add_main_option(
            "log-level",
            ord("l"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            "Set log level (DEBUG, INFO, WARNING, ERROR)",
            "LEVEL",
        )

    def do_handle_local_options(self, options):
        """Handle command-line options."""
        # Configure logging based on options
        log_level = logging.INFO

        if options.contains("debug"):
            log_level = logging.DEBUG
        elif options.contains("log-level"):
            level_str = options.lookup_value("log-level").get_string().upper()
            log_level = getattr(logging, level_str, logging.INFO)

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%H:%M:%S",
        )

        logger.info("Starting GTKPass application")
        logger.debug(f"Log level: {logging.getLevelName(log_level)}")

        return -1  # Continue processing

    def do_command_line(self, command_line):
        """Handle command line."""
        self.activate()
        return 0

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
            application_icon=APP_ID,
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
