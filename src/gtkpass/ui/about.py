"""About dialog.

Everything static is declared in blueprints/about.blp; only the version, which
comes from the installed distribution, is filled in here.
"""

import importlib.metadata
import importlib.resources

from gtkpass._gi import Adw, Gtk

UI = importlib.resources.files("gtkpass.ui.blueprints")

#: What pip and the RPM know this project as; see pyproject.toml.
DISTRIBUTION_NAME = "gtk-pass-ng"


def _version() -> str:
    try:
        # The distribution, not the import name: PyPI holds ``gtkpass`` for an
        # unrelated project, so this one ships as gtk-pass-ng. Asked for by
        # the wrong name it answered "unknown" in every build there was.
        return importlib.metadata.version(DISTRIBUTION_NAME)
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
