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

    #: What --log-level accepts. getattr on the logging module accepted any
    #: attribute name, so --log-level=basicConfig passed a function as the level
    #: and the application died on startup rather than saying what was wrong.
    LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

    def do_handle_local_options(self, options):
        """Handle command-line options."""
        # Configure logging based on options
        log_level = logging.INFO
        unknown = ""

        if options.contains("debug"):
            log_level = logging.DEBUG
        elif options.contains("log-level"):
            level_str = options.lookup_value("log-level").get_string().upper()
            if level_str in self.LOG_LEVELS:
                log_level = getattr(logging, level_str)
            else:
                unknown = level_str

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%H:%M:%S",
        )

        if unknown:
            logger.warning(
                "Unknown log level %r; using INFO. Known levels: %s",
                unknown,
                ", ".join(self.LOG_LEVELS),
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

    def do_shutdown(self):
        """Leave nothing of a copied secret behind on the way out.

        The clipboard timeout cannot fire once the process is gone, so quitting
        inside it would otherwise leave the password there indefinitely. This is
        the application's job rather than the window's: closing the last window
        and Ctrl+Q both arrive here, while neither reliably destroys a window
        that other references are still holding.
        """
        if self.window is not None:
            self.window.discard_clipboard()
        Adw.Application.do_shutdown(self)

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
        """Show the preferences dialog."""
        from gtkpass.ui.settings import SettingsWindow

        SettingsWindow().present(self.window)

    def _on_about_action(self, action: Gio.SimpleAction, param):
        """Show the about dialog."""
        from gtkpass.ui.about import build_about_dialog

        build_about_dialog().present(self.window)


def main():
    """Run the application."""
    app = GTKPassApp()
    return app.run(sys.argv)
