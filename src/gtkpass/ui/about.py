"""About dialog.

Everything static is declared in blueprints/about.blp; only the version, which
comes from the installed distribution, is filled in here.
"""

import importlib.metadata
import importlib.resources

from gtkpass._gi import Adw, Gtk

UI = importlib.resources.files("gtkpass.ui.blueprints")


def _version() -> str:
    try:
        return importlib.metadata.version("gtkpass")
    except importlib.metadata.PackageNotFoundError:
        # Running from a source tree that was never installed.
        return "unknown"


def build_about_dialog() -> Adw.AboutDialog:
    """Load the about dialog from its blueprint.

    Adw.AboutDialog is final, so this is a plain builder object rather than a
    Gtk.Template subclass.
    """
    builder = Gtk.Builder.new_from_file(str(UI / "about.ui"))
    dialog = builder.get_object("about_dialog")
    dialog.set_version(_version())
    return dialog
