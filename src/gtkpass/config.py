"""Application identity and GSettings access.

Every identifier the desktop cares about — the D-Bus name, the ``.desktop``
file, the icon, the AppStream component, the WM class — has to be one and the
same string, so it is defined once here.
"""

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio  # noqa: E402

#: Reverse-DNS application identifier, following the GNOME/Flathub convention.
APP_ID = "io.github.RonnyPfannschmidt.GTKPass"

#: Identifier of the top level GSettings schema.
SCHEMA_ID = APP_ID

#: Object path of the top level schema, derived from APP_ID as GLib expects.
SCHEMA_PATH = "/" + APP_ID.replace(".", "/") + "/"

#: Relocatable schema identifier for per-backend configuration.
BACKEND_SCHEMA_ID = SCHEMA_ID + ".backend.{backend_type}"

#: Object path for a backend instance's relocatable schema.
BACKEND_SCHEMA_PATH = SCHEMA_PATH + "backends/{backend_id}/"


class SchemaNotInstalledError(RuntimeError):
    """Raised when the GSettings schema cannot be found."""


def _lookup(schema_id: str) -> Gio.SettingsSchema:
    """Resolve a schema, or raise something a human can act on.

    ``Gio.Settings.new()`` on an unknown schema calls ``g_error()``, which
    aborts the process outright — it is not a Python exception and leaves no
    traceback.  Always look the schema up first.
    """
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(schema_id, True) if source is not None else None
    if schema is None:
        raise SchemaNotInstalledError(
            f"GSettings schema {schema_id!r} is not installed.\n"
            f"Run 'glib-compile-schemas data/' and set "
            f"GSETTINGS_SCHEMA_DIR to that directory, or install the schema "
            f"into a system schema directory."
        )
    return schema


def get_settings() -> Gio.Settings:
    """Settings for the application itself."""
    return Gio.Settings.new_full(_lookup(SCHEMA_ID), None, None)


def get_backend_settings(backend_type: str, backend_id: str) -> Gio.Settings:
    """Settings for one configured backend instance.

    Args:
        backend_type: Which backend implementation (``demo``, ``pass``, ...).
        backend_id: Unique identifier of this configured instance.
    """
    schema_id = BACKEND_SCHEMA_ID.format(backend_type=backend_type)
    path = BACKEND_SCHEMA_PATH.format(backend_id=backend_id)
    return Gio.Settings.new_full(_lookup(schema_id), None, path)
