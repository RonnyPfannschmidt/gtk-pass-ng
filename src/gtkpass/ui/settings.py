"""Settings window for GTKPass.

Provides UI for configuring backends and application settings.
"""

from pathlib import Path
from typing import ClassVar

from gtkpass._gi import Adw, GLib, GObject, Gtk
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


class BackendSettingsRow(Adw.PreferencesRow):
    """Row for managing backend instance settings."""

    __gsignals__: ClassVar[dict] = {
        "remove-backend": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "settings-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(
        self,
        backend_type: str,
        backend_id: str,
        settings: BackendSettings | None = None,
    ):
        """Initialize backend settings row.

        Args:
            backend_type: Type of backend (demo, secretservice, pass, direct)
            backend_id: Unique ID for this backend instance
            settings: Current settings for the backend
        """
        super().__init__()
        self.backend_type = backend_type
        self.backend_id = backend_id
        self.settings = settings or self._get_default_settings()

        # Build UI
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Header with backend type and remove button
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        # Backend name entry
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        name_label = Gtk.Label(label="Name:", xalign=0)
        name_label.add_css_class("caption")
        self.name_entry = Gtk.Entry(
            text=self._get_friendly_name(),
            hexpand=True,
            placeholder_text=f"{backend_type.title()} Backend",
        )
        self.name_entry.connect("changed", lambda e: self.emit("settings-changed"))
        name_box.append(name_label)
        name_box.append(self.name_entry)
        header_box.append(name_box)

        remove_btn = Gtk.Button(
            icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER
        )
        remove_btn.add_css_class("destructive-action")
        remove_btn.set_tooltip_text("Remove this backend")
        remove_btn.connect("clicked", lambda _: self.emit("remove-backend"))
        header_box.append(remove_btn)

        box.append(header_box)

        # Backend-specific settings
        self.settings_group = Adw.PreferencesGroup()
        self._build_settings_ui()
        box.append(self.settings_group)

        self.set_child(box)

    def _get_friendly_name(self) -> str:
        """Name to prefill the entry with: the stored one, or a derived one."""
        return get_backend_display_name(self.backend_type, self.backend_id)

    def get_display_name(self) -> str:
        """Name currently typed in the entry, empty if the user cleared it."""
        return self.name_entry.get_text().strip()

    def _get_default_settings(self) -> BackendSettings:
        """Get default settings for backend type."""
        if self.backend_type == "demo":
            return DemoBackendSettings()
        elif self.backend_type == "secretservice":
            return SecretServiceBackendSettings()
        elif self.backend_type == "pass":
            return PassBackendSettings()
        elif self.backend_type == "direct":
            return DirectBackendSettings()
        return BackendSettings()

    def _build_settings_ui(self):
        """Build backend-specific settings UI."""
        if self.backend_type == "demo":
            self._build_demo_settings()
        elif self.backend_type == "secretservice":
            self._build_secretservice_settings()
        elif self.backend_type == "pass":
            self._build_pass_settings()
        elif self.backend_type == "direct":
            self._build_direct_settings()

    def _build_demo_settings(self):
        """Build settings UI for demo backend."""
        settings: DemoBackendSettings = self.settings

        # Custom data path
        row = Adw.ActionRow(
            title="Custom Data Path", subtitle="Optional path to custom demo.json"
        )
        entry = Gtk.Entry(
            text=str(settings.custom_data_path) if settings.custom_data_path else "",
            hexpand=True,
            placeholder_text="/path/to/custom/demo.json",
        )
        entry.connect(
            "changed",
            lambda e: (
                setattr(
                    self.settings,
                    "custom_data_path",
                    Path(e.get_text()).expanduser() if e.get_text() else None,
                ),
                self.emit("settings-changed"),
            ),
        )
        row.add_suffix(entry)
        self.settings_group.add(row)

    def _build_secretservice_settings(self):
        """Build settings UI for Secret Service backend."""
        settings: SecretServiceBackendSettings = self.settings

        # Collection name
        row = Adw.ActionRow(
            title="Collection Name", subtitle="Name of the keyring collection to use"
        )
        entry = Gtk.Entry(text=settings.collection_name, hexpand=True)
        entry.connect(
            "changed",
            lambda e: (
                setattr(self.settings, "collection_name", e.get_text()),
                self.emit("settings-changed"),
            ),
        )
        row.add_suffix(entry)
        self.settings_group.add(row)

    def _build_pass_settings(self):
        """Build settings UI for Pass CLI backend."""
        settings: PassBackendSettings = self.settings

        # Password store directory
        row = Adw.ActionRow(
            title="Password Store Directory",
            subtitle="Path to password store (empty = use default)",
        )
        entry = Gtk.Entry(
            text=str(settings.password_store_dir)
            if settings.password_store_dir
            else "",
            hexpand=True,
            placeholder_text="~/.password-store",
        )
        entry.connect(
            "changed",
            lambda e: (
                setattr(
                    self.settings,
                    "password_store_dir",
                    Path(e.get_text()).expanduser() if e.get_text() else None,
                ),
                self.emit("settings-changed"),
            ),
        )
        row.add_suffix(entry)
        self.settings_group.add(row)

        # Use git
        row = Adw.SwitchRow(title="Enable Git", subtitle="Use git for version control")
        row.set_active(settings.use_git)
        row.connect(
            "notify::active",
            lambda r, _: (
                setattr(self.settings, "use_git", r.get_active()),
                self.emit("settings-changed"),
            ),
        )
        self.settings_group.add(row)

    def _build_direct_settings(self):
        """Build settings UI for Direct backend."""
        settings: DirectBackendSettings = self.settings

        # Password store directory
        row = Adw.ActionRow(
            title="Password Store Directory",
            subtitle="Path to password store (empty = use default)",
        )
        entry = Gtk.Entry(
            text=str(settings.password_store_dir)
            if settings.password_store_dir
            else "",
            hexpand=True,
            placeholder_text="~/.password-store",
        )
        entry.connect(
            "changed",
            lambda e: (
                setattr(
                    self.settings,
                    "password_store_dir",
                    Path(e.get_text()).expanduser() if e.get_text() else None,
                ),
                self.emit("settings-changed"),
            ),
        )
        row.add_suffix(entry)
        self.settings_group.add(row)

        # GPG home
        row = Adw.ActionRow(
            title="GPG Home Directory", subtitle="Custom GPG home (empty = use default)"
        )
        entry = Gtk.Entry(
            text=str(settings.gpg_home) if settings.gpg_home else "",
            hexpand=True,
            placeholder_text="~/.gnupg",
        )
        entry.connect(
            "changed",
            lambda e: (
                setattr(
                    self.settings,
                    "gpg_home",
                    Path(e.get_text()).expanduser() if e.get_text() else None,
                ),
                self.emit("settings-changed"),
            ),
        )
        row.add_suffix(entry)
        self.settings_group.add(row)

    def get_settings(self) -> BackendSettings:
        """Get current settings."""
        return self.settings


class SettingsWindow(Adw.PreferencesWindow):
    """Settings window for GTKPass."""

    def __init__(self, **kwargs):
        """Initialize settings window."""
        super().__init__(**kwargs)
        self.set_title("Settings")
        self.set_default_size(600, 500)

        # GSettings
        self.settings = get_settings()

        # Backend instances
        self.backend_instances: dict[str, BackendSettings] = {}
        self.backend_rows: dict[str, BackendSettingsRow] = {}

        # Backends page
        backends_page = Adw.PreferencesPage(
            title="Backends", icon_name="network-server-symbolic"
        )

        # Active backends group
        self.backends_group = Adw.PreferencesGroup(
            title="Active Backends", description="Manage password backend instances"
        )
        backends_page.add(self.backends_group)

        # Load saved backend configurations
        self._load_backend_configs()

        # Add backend group
        add_group = Adw.PreferencesGroup(title="Add New Backend")

        # Backend type selector
        backend_types = ["demo", "secretservice", "pass", "direct"]
        self.backend_combo = Gtk.ComboBoxText()
        for backend_type in backend_types:
            self.backend_combo.append(backend_type, backend_type.title())
        self.backend_combo.set_active(0)

        combo_row = Adw.ActionRow(
            title="Backend Type", subtitle="Select type of backend to add"
        )
        combo_row.add_suffix(self.backend_combo)
        combo_row.set_activatable_widget(self.backend_combo)
        add_group.add(combo_row)

        # Add button
        add_btn = Gtk.Button(label="Add Backend", halign=Gtk.Align.START)
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add_backend)
        add_row = Adw.ActionRow()
        add_row.add_suffix(add_btn)
        add_group.add(add_row)

        backends_page.add(add_group)

        self.add(backends_page)

        # General settings page
        general_page = Adw.PreferencesPage(
            title="General", icon_name="preferences-other-symbolic"
        )

        # Appearance group
        appearance_group = Adw.PreferencesGroup(title="Appearance")

        # Dark mode switch
        dark_mode_row = Adw.SwitchRow(
            title="Dark Mode", subtitle="Use dark color scheme"
        )
        appearance_group.add(dark_mode_row)

        general_page.add(appearance_group)

        # Security group
        security_group = Adw.PreferencesGroup(title="Security")

        # Auto-clear timeout
        timeout_row = Adw.SpinRow(
            title="Auto-clear Timeout",
            subtitle="Seconds before clearing password from memory (0 = never)",
            adjustment=Gtk.Adjustment(
                lower=0, upper=300, step_increment=10, page_increment=60, value=30
            ),
        )
        security_group.add(timeout_row)

        general_page.add(security_group)

        self.add(general_page)

    def _load_backend_configs(self):
        """Load backend configurations from GSettings."""
        try:
            # Get list of backend instances
            instances = self.settings.get_value("backend-instances")

            for backend_id, backend_type in instances:
                # Create settings for this backend instance
                backend_settings = self._load_backend_settings(backend_id, backend_type)
                if backend_settings:
                    # Create UI row
                    row = BackendSettingsRow(backend_type, backend_id, backend_settings)
                    row.connect("remove-backend", self._on_remove_backend)
                    row.connect(
                        "settings-changed", lambda r: self._save_backend_configs()
                    )
                    self.backends_group.add(row)

                    # Store references
                    self.backend_instances[backend_id] = backend_settings
                    self.backend_rows[backend_id] = row
        except Exception as e:
            print(f"Error loading backend configs: {e}")

    def _load_backend_settings(
        self, backend_id: str, backend_type: str
    ) -> BackendSettings | None:
        """Load settings for a specific backend instance from GSettings."""
        try:
            # Create settings object for this backend path
            backend_gsettings = get_backend_settings(backend_type, backend_id)

            # Read settings based on backend type
            if backend_type == "demo":
                custom_path = backend_gsettings.get_string("custom-data-path")
                return DemoBackendSettings(
                    custom_data_path=Path(custom_path) if custom_path else None
                )
            elif backend_type == "secretservice":
                collection_name = backend_gsettings.get_string("collection-name")
                return SecretServiceBackendSettings(collection_name=collection_name)
            elif backend_type == "pass":
                store_dir = backend_gsettings.get_string("password-store-dir")
                use_git = backend_gsettings.get_boolean("use-git")
                return PassBackendSettings(
                    password_store_dir=Path(store_dir) if store_dir else None,
                    use_git=use_git,
                )
            elif backend_type == "direct":
                store_dir = backend_gsettings.get_string("password-store-dir")
                gpg_home = backend_gsettings.get_string("gpg-home")
                return DirectBackendSettings(
                    password_store_dir=Path(store_dir) if store_dir else None,
                    gpg_home=Path(gpg_home) if gpg_home else None,
                )
        except Exception as e:
            print(
                f"Error loading settings for {backend_type} backend {backend_id}: {e}"
            )
        return None

    def _save_backend_configs(self):
        """Save backend configurations to GSettings."""
        # Build list of backend instances
        instances = []
        for backend_id, row in self.backend_rows.items():
            instances.append((backend_id, row.backend_type))

            # Save settings for this backend
            self._save_backend_settings(
                backend_id, row.backend_type, row.get_settings()
            )
            set_backend_display_name(
                row.backend_type, backend_id, row.get_display_name()
            )

        # Save instance list
        variant = GLib.Variant("a(ss)", instances)
        self.settings.set_value("backend-instances", variant)

    def _save_backend_settings(
        self, backend_id: str, backend_type: str, settings: BackendSettings
    ):
        """Save settings for a specific backend instance to GSettings."""
        try:
            # Create settings object for this backend path
            backend_gsettings = get_backend_settings(backend_type, backend_id)

            # Write settings based on backend type
            if isinstance(settings, DemoBackendSettings):
                backend_gsettings.set_string(
                    "custom-data-path",
                    str(settings.custom_data_path) if settings.custom_data_path else "",
                )
            elif isinstance(settings, SecretServiceBackendSettings):
                backend_gsettings.set_string(
                    "collection-name", settings.collection_name
                )
            elif isinstance(settings, PassBackendSettings):
                backend_gsettings.set_string(
                    "password-store-dir",
                    str(settings.password_store_dir)
                    if settings.password_store_dir
                    else "",
                )
                backend_gsettings.set_boolean("use-git", settings.use_git)
            elif isinstance(settings, DirectBackendSettings):
                backend_gsettings.set_string(
                    "password-store-dir",
                    str(settings.password_store_dir)
                    if settings.password_store_dir
                    else "",
                )
                backend_gsettings.set_string(
                    "gpg-home", str(settings.gpg_home) if settings.gpg_home else ""
                )
        except Exception as e:
            print(f"Error saving settings for {backend_type} backend {backend_id}: {e}")

    def _on_remove_backend(self, row: BackendSettingsRow):
        """Handle backend removal."""
        backend_id = row.backend_id
        backend_type = row.backend_type

        # Remove from UI
        self.backends_group.remove(row)

        # Remove from storage
        if backend_id in self.backend_instances:
            del self.backend_instances[backend_id]
        if backend_id in self.backend_rows:
            del self.backend_rows[backend_id]

        # Clear the backend's GSettings
        try:
            backend_gsettings = get_backend_settings(backend_type, backend_id)

            # Reset all keys to defaults
            for key in backend_gsettings.list_keys():
                backend_gsettings.reset(key)
        except Exception as e:
            print(
                f"Error clearing settings for {backend_type} backend {backend_id}: {e}"
            )

        # Save updated instance list
        self._save_backend_configs()

    def _on_add_backend(self, button):
        """Handle add backend button click."""
        backend_type = self.backend_combo.get_active_id()
        if not backend_type:
            return

        # Generate unique ID
        import time

        backend_id = f"{backend_type}_{int(time.time())}"

        # Create settings row
        settings_row = BackendSettingsRow(backend_type, backend_id)
        settings_row.connect("remove-backend", self._on_remove_backend)
        settings_row.connect("settings-changed", lambda r: self._save_backend_configs())
        self.backends_group.add(settings_row)

        # Store references
        self.backend_instances[backend_id] = settings_row.get_settings()
        self.backend_rows[backend_id] = settings_row

        # Save configuration
        self._save_backend_configs()

    def get_backend_configurations(self) -> dict[str, tuple[str, BackendSettings]]:
        """Get all configured backend instances.

        Returns:
            Dict mapping backend_id to (backend_type, settings) tuples
        """
        configs = {}
        # TODO: Iterate through backends_group children
        return configs
