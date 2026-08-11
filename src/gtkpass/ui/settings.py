"""Settings window.

The widgets live in blueprints/preferences.blp and blueprints/backend_row.blp;
this module only maps them onto BackendSettings objects and GSettings.
"""

import importlib.resources
import logging
from pathlib import Path
from typing import ClassVar

from gtkpass._gi import Adw, Gio, GLib, GObject, Gtk
from gtkpass.backends import BackendSettings
from gtkpass.backends.demo import DemoBackendSettings
from gtkpass.backends.direct import DirectBackendSettings
from gtkpass.backends.pass_cli import PassBackendSettings
from gtkpass.backends.secretservice import SecretServiceBackendSettings
from gtkpass.config import (
    get_backend_display_name,
    get_backend_settings,
    get_settings,
    set_backend_display_name,
)

#: Order matters: it is the order of the combo row's model in preferences.blp.
BACKEND_TYPES = ("demo", "secretservice", "pass", "direct")

UI = importlib.resources.files("gtkpass.ui.blueprints")

logger = logging.getLogger(__name__)


def _optional_path(text: str) -> Path | None:
    """Interpret an entry's contents as a path, treating empty as unset."""
    text = text.strip()
    return Path(text).expanduser() if text else None


@Gtk.Template(filename=str(UI / "backend_row.ui"))
class BackendSettingsRow(Adw.ExpanderRow):
    """One configured backend instance."""

    __gtype_name__ = "BackendSettingsRow"

    __gsignals__: ClassVar[dict] = {
        "remove-backend": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "settings-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    name_row = Gtk.Template.Child()
    demo_path_row = Gtk.Template.Child()
    secretservice_collection_row = Gtk.Template.Child()
    pass_store_row = Gtk.Template.Child()
    pass_git_row = Gtk.Template.Child()
    direct_store_row = Gtk.Template.Child()
    direct_gpg_home_row = Gtk.Template.Child()
    remove_button = Gtk.Template.Child()
    demo_path_button = Gtk.Template.Child()
    pass_store_button = Gtk.Template.Child()
    direct_store_button = Gtk.Template.Child()
    direct_gpg_home_button = Gtk.Template.Child()

    #: Which of the declared rows belong to which backend type.
    ROWS_BY_TYPE: ClassVar[dict[str, tuple[str, ...]]] = {
        "demo": ("demo_path_row",),
        "secretservice": ("secretservice_collection_row",),
        "pass": ("pass_store_row", "pass_git_row"),
        "direct": ("direct_store_row", "direct_gpg_home_row"),
    }

    def __init__(
        self,
        backend_type: str,
        backend_id: str,
        settings: BackendSettings | None = None,
    ):
        super().__init__()
        self.backend_type = backend_type
        self.backend_id = backend_id
        self.settings = settings or self._default_settings()
        # Suppress the change signals emitted while filling the rows in.
        self._loading = True

        self.set_title(get_backend_display_name(backend_type, backend_id))
        self.set_subtitle(backend_type)
        self.name_row.set_text(self.get_title())

        for row_name in self.ROWS_BY_TYPE.get(backend_type, ()):
            getattr(self, row_name).set_visible(True)
        self._load_into_rows()
        self._loading = False

    def _default_settings(self) -> BackendSettings:
        return {
            "demo": DemoBackendSettings,
            "secretservice": SecretServiceBackendSettings,
            "pass": PassBackendSettings,
            "direct": DirectBackendSettings,
        }.get(self.backend_type, BackendSettings)()

    def _load_into_rows(self) -> None:
        """Show the current settings in the rows for this backend type."""
        settings = self.settings
        if isinstance(settings, DemoBackendSettings):
            self.demo_path_row.set_text(str(settings.custom_data_path or ""))
        elif isinstance(settings, SecretServiceBackendSettings):
            self.secretservice_collection_row.set_text(settings.collection_name)
        elif isinstance(settings, PassBackendSettings):
            self.pass_store_row.set_text(str(settings.password_store_dir or ""))
            self.pass_git_row.set_active(settings.use_git)
        elif isinstance(settings, DirectBackendSettings):
            self.direct_store_row.set_text(str(settings.password_store_dir or ""))
            self.direct_gpg_home_row.set_text(str(settings.gpg_home or ""))

    def _read_from_rows(self) -> None:
        """Copy the rows back into the settings object."""
        settings = self.settings
        if isinstance(settings, DemoBackendSettings):
            settings.custom_data_path = _optional_path(self.demo_path_row.get_text())
        elif isinstance(settings, SecretServiceBackendSettings):
            settings.collection_name = self.secretservice_collection_row.get_text()
        elif isinstance(settings, PassBackendSettings):
            settings.password_store_dir = _optional_path(self.pass_store_row.get_text())
            settings.use_git = self.pass_git_row.get_active()
        elif isinstance(settings, DirectBackendSettings):
            settings.password_store_dir = _optional_path(
                self.direct_store_row.get_text()
            )
            settings.gpg_home = _optional_path(self.direct_gpg_home_row.get_text())

    @Gtk.Template.Callback()
    def _on_settings_changed(self, *_args) -> None:
        if self._loading:
            return
        self._read_from_rows()
        self.set_title(self.get_display_name() or self.backend_type.title())
        self.emit("settings-changed")

    @Gtk.Template.Callback()
    def _on_remove_clicked(self, *_args) -> None:
        self.emit("remove-backend")

    # -- choosing a path -----------------------------------------------------

    def _chooser_for(self, button) -> tuple[Adw.EntryRow, bool] | None:
        """Which row a chooser button fills in, and whether it wants a folder.

        One handler for all of them rather than four that differ in a name:
        Blueprint can point every button at the same callback, and the button
        that was pressed says the rest.
        """
        targets = {
            self.demo_path_button: (self.demo_path_row, False),
            self.pass_store_button: (self.pass_store_row, True),
            self.direct_store_button: (self.direct_store_row, True),
            self.direct_gpg_home_button: (self.direct_gpg_home_row, True),
        }
        return targets.get(button)

    @Gtk.Template.Callback()
    def _on_choose(self, button) -> None:
        """Ask for a path with the file chooser rather than by typing.

        Under Flatpak this is not a convenience. Choosing through the chooser
        goes through the portal, and that is what grants the sandbox access to
        the directory -- so a store typed in by hand is one the application
        then cannot open, and says so only later and in terms of GPG.
        """
        chooser = self._chooser_for(button)
        if chooser is None:
            return
        row, folder = chooser

        dialog = Gtk.FileDialog(
            title="Choose a Folder" if folder else "Choose a File",
            modal=True,
        )
        current = _optional_path(row.get_text())
        if current is not None and current.exists():
            dialog.set_initial_folder(
                Gio.File.new_for_path(str(current if folder else current.parent))
            )

        window = self.get_root()
        if folder:
            dialog.select_folder(window, None, self._chosen, (row, True))
        else:
            dialog.open(window, None, self._chosen, (row, False))

    def _chosen(self, dialog, result, target) -> None:
        """Take the answer, or let a cancelled chooser pass in silence."""
        row, folder = target
        try:
            chosen = (
                dialog.select_folder_finish(result)
                if folder
                else dialog.open_finish(result)
            )
        except GLib.Error as e:
            # Dismissing the chooser is not a failure worth reporting.
            logger.debug("No path was chosen: %s", e)
            return
        self.apply_choice(row, chosen)

    def apply_choice(self, row, chosen) -> None:
        """Put a chosen path in its row, which saves it as typing would.

        Separate from the chooser so that it can be exercised: a GtkFileDialog
        cannot be driven from a test, and this is the half that has anything to
        get wrong.
        """
        path = chosen.get_path() if chosen is not None else None
        if path:
            row.set_text(path)

    def get_display_name(self) -> str:
        """Name currently typed in the entry, empty if the user cleared it."""
        return self.name_row.get_text().strip()

    def get_settings(self) -> BackendSettings:
        return self.settings


@Gtk.Template(filename=str(UI / "preferences.ui"))
class SettingsWindow(Adw.PreferencesDialog):
    """Preferences: backend instances and application-wide options."""

    __gtype_name__ = "SettingsWindow"

    backends_group = Gtk.Template.Child()
    backend_combo = Gtk.Template.Child()
    add_backend_button = Gtk.Template.Child()
    show_hidden_row = Gtk.Template.Child()
    clipboard_timeout_row = Gtk.Template.Child()
    search_as_you_type_row = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.settings = get_settings()
        self.backend_instances: dict[str, BackendSettings] = {}
        self.backend_rows: dict[str, BackendSettingsRow] = {}

        self._bind_general_page()
        self._load_backend_configs()

    def _bind_general_page(self) -> None:
        """Wire the application-wide rows straight to GSettings.

        These keys existed in the schema from the start but nothing read or
        wrote them, so the page was decoration.
        """
        self.settings.bind(
            "show-hidden-passwords",
            self.show_hidden_row,
            "active",
            Gio.SettingsBindFlags.DEFAULT,
        )
        self.settings.bind(
            "search-as-you-type",
            self.search_as_you_type_row,
            "active",
            Gio.SettingsBindFlags.DEFAULT,
        )
        self.settings.bind(
            "clipboard-timeout",
            self.clipboard_timeout_row.get_adjustment(),
            "value",
            Gio.SettingsBindFlags.DEFAULT,
        )

    # -- backend instances ---------------------------------------------------

    def _load_backend_configs(self) -> None:
        """Build a row for every backend instance recorded in GSettings."""
        for backend_id, backend_type in self.settings.get_value("backend-instances"):
            settings = self._load_backend_settings(backend_id, backend_type)
            if settings is None:
                continue
            self._add_row(backend_id, backend_type, settings)

    def _add_row(
        self, backend_id: str, backend_type: str, settings: BackendSettings | None
    ) -> BackendSettingsRow:
        row = BackendSettingsRow(backend_type, backend_id, settings)
        row.connect("remove-backend", self._on_remove_backend)
        row.connect("settings-changed", lambda _row: self._save_backend_configs())
        self.backends_group.add(row)
        self.backend_instances[backend_id] = settings
        self.backend_rows[backend_id] = row
        return row

    def _load_backend_settings(
        self, backend_id: str, backend_type: str
    ) -> BackendSettings | None:
        """Read one instance's settings out of its relocatable schema."""
        try:
            stored = get_backend_settings(backend_type, backend_id)
        except Exception as e:
            logger.warning("Cannot read settings for %s: %s", backend_id, e)
            return None

        if backend_type == "demo":
            return DemoBackendSettings(
                custom_data_path=_optional_path(stored.get_string("custom-data-path"))
            )
        if backend_type == "secretservice":
            return SecretServiceBackendSettings(
                collection_name=stored.get_string("collection-name")
            )
        if backend_type == "pass":
            return PassBackendSettings(
                password_store_dir=_optional_path(
                    stored.get_string("password-store-dir")
                ),
                use_git=stored.get_boolean("use-git"),
            )
        if backend_type == "direct":
            return DirectBackendSettings(
                password_store_dir=_optional_path(
                    stored.get_string("password-store-dir")
                ),
                gpg_home=_optional_path(stored.get_string("gpg-home")),
            )
        logger.warning("Unknown backend type: %s", backend_type)
        return None

    def _save_backend_configs(self) -> None:
        """Persist every row: the instance list, per-backend settings, names."""
        instances = []
        for backend_id, row in self.backend_rows.items():
            instances.append((backend_id, row.backend_type))
            self._save_backend_settings(
                backend_id, row.backend_type, row.get_settings()
            )
            set_backend_display_name(
                row.backend_type, backend_id, row.get_display_name()
            )
        self.settings.set_value("backend-instances", GLib.Variant("a(ss)", instances))

    def _save_backend_settings(
        self, backend_id: str, backend_type: str, settings: BackendSettings
    ) -> None:
        stored = get_backend_settings(backend_type, backend_id)
        if isinstance(settings, DemoBackendSettings):
            stored.set_string("custom-data-path", str(settings.custom_data_path or ""))
        elif isinstance(settings, SecretServiceBackendSettings):
            stored.set_string("collection-name", settings.collection_name)
        elif isinstance(settings, PassBackendSettings):
            stored.set_string(
                "password-store-dir", str(settings.password_store_dir or "")
            )
            stored.set_boolean("use-git", settings.use_git)
        elif isinstance(settings, DirectBackendSettings):
            stored.set_string(
                "password-store-dir", str(settings.password_store_dir or "")
            )
            stored.set_string("gpg-home", str(settings.gpg_home or ""))

    def _new_backend_id(self, backend_type: str) -> str:
        """An id no configured instance is already using.

        The wall clock in whole seconds is a readable stem and a poor
        identifier: two backends of the same type added in the same second were
        given the same one, which meant one row on screen where two had been
        asked for, and both instances reading and writing the same relocatable
        schema path -- one store's settings holding the other's.

        Taken ids are read back from GSettings as well as from the rows, so an
        instance this dialog could not load does not have its id handed out
        from underneath it.
        """
        taken = set(self.backend_rows)
        taken.update(
            backend_id for backend_id, _ in self.settings.get_value("backend-instances")
        )

        stem = f"{backend_type}_{GLib.get_real_time() // 1_000_000}"
        if stem not in taken:
            return stem
        suffix = 2
        while f"{stem}_{suffix}" in taken:
            suffix += 1
        return f"{stem}_{suffix}"

    @Gtk.Template.Callback()
    def _on_add_backend(self, _button) -> None:
        """Add an instance of the type selected in the combo row."""
        backend_type = BACKEND_TYPES[self.backend_combo.get_selected()]
        backend_id = self._new_backend_id(backend_type)

        row = self._add_row(backend_id, backend_type, None)
        row.set_expanded(True)
        self._save_backend_configs()

    def _on_remove_backend(self, row: BackendSettingsRow) -> None:
        self.backends_group.remove(row)
        self.backend_rows.pop(row.backend_id, None)
        self.backend_instances.pop(row.backend_id, None)

        try:
            stored = get_backend_settings(row.backend_type, row.backend_id)
            for key in stored.list_keys():
                stored.reset(key)
        except Exception as e:
            logger.warning("Could not clear settings for %s: %s", row.backend_id, e)

        self._save_backend_configs()
