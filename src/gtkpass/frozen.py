"""What a frozen bundle has to arrange for itself.

The Windows build is a PyInstaller bundle: the interpreter, GTK4, libadwaita,
the icon theme and this application in one directory, unpacked wherever the
installer put it or wherever the user unzipped it. Nothing in there is on a
path GLib would look at, and there is no launcher script to say so -- the same
constraint the RPM and the sysext image are built under, arriving from the other
direction.

PyInstaller's own runtime hooks cover most of it: ``GI_TYPELIB_PATH`` for the
typelibs, ``GDK_PIXBUF_MODULE_FILE`` for the loader cache that renders every
symbolic icon in the interface, and ``XDG_DATA_DIRS`` for the icon theme. What
they do not cover is the GSettings schema, and that one is not optional: the
application reads its configuration before it draws anything.

``XDG_DATA_DIRS`` would in principle be enough for the schema too, GLib building
its default schema source out of the system data directories. It is honoured on
Windows only when it is set, and it is what a frozen bundle's *whole* data
lookup already rests on, so leaving the schema to depend on it as well would put
the application's own configuration behind the same single point of failure as
its icons. ``GSETTINGS_SCHEMA_DIR`` is read unconditionally on every platform,
so the schema is pointed at directly.
"""

import os
import sys
from pathlib import Path

#: Where a bundle keeps its compiled schema, relative to the unpacked root.
#:
#: A data directory in the ordinary layout rather than somewhere of this
#: application's own choosing, because ``XDG_DATA_DIRS`` points at ``share/``
#: and GLib looks under it in exactly this shape.
SCHEMA_SUBDIR = Path("share") / "glib-2.0" / "schemas"

#: Written by ``glib-compile-schemas``; the XML alongside it is not read at
#: runtime. Its absence means the build never compiled anything.
COMPILED_SCHEMA = "gschemas.compiled"


def is_frozen() -> bool:
    """Whether this is running out of a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_root() -> Path | None:
    """Where the bundle was unpacked, or None outside one.

    ``sys._MEIPASS`` is the directory PyInstaller resolves its own data
    against -- next to the executable for a onedir build, a temporary
    directory for a onefile one.
    """
    if not is_frozen():
        return None
    # Set by the PyInstaller bootloader and by nothing else, so there is no
    # declaration of it for a type checker to have seen.
    return Path(sys._MEIPASS)  # type: ignore[attr-defined]


def schema_dir() -> Path | None:
    """The bundle's compiled schema directory, if it has one.

    Returns None when there is no compiled schema, rather than a directory that
    happens to exist. A build that did not compile the schema is a broken build,
    and it should fail saying the schema is not installed -- which
    :func:`gtkpass.config.get_settings` does, naming it -- instead of GLib
    reporting a missing schema from a directory that was pointed at on faith.
    """
    root = bundle_root()
    if root is None:
        return None
    directory = root / SCHEMA_SUBDIR
    return directory if (directory / COMPILED_SCHEMA).is_file() else None


def configure_environment() -> None:
    """Point GLib at what the bundle carries. A no-op anywhere else.

    Called from ``gtkpass/__init__.py``, which is imported before anything
    reaches ``gi.repository``: GLib caches its default schema source the first
    time it is asked, so setting this afterwards would change nothing.

    Appends rather than replaces. ``GSETTINGS_SCHEMA_DIR`` is a search path, and
    an entry already in it was put there by someone who meant it -- the test
    suite, or a developer pointing a build at a schema they are editing. The
    bundle is the fallback, and the only place its own schema exists.
    """
    directory = schema_dir()
    if directory is None:
        return

    configured = os.environ.get("GSETTINGS_SCHEMA_DIR", "")
    entries = [entry for entry in configured.split(os.pathsep) if entry]
    if str(directory) not in entries:
        entries.append(str(directory))
    os.environ["GSETTINGS_SCHEMA_DIR"] = os.pathsep.join(entries)
