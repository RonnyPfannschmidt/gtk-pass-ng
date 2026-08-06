"""Single place where the GObject Introspection versions are pinned.

``gi.require_version`` has to run before anything imports from
``gi.repository``, which otherwise forces every module to interleave a bare
statement with its imports.  Importing the names from here instead keeps the
requirement in one place, makes it impossible to forget, and leaves every other
module with an ordinary import block.

Import from this module rather than from ``gi.repository`` directly::

    from gtkpass._gi import Adw, Gtk
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

__all__ = ["Adw", "GLib", "GObject", "Gdk", "Gio", "Gtk"]
