"""Main application window."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk, GLib  # noqa: E402
from pathlib import Path

from gtkpass.backends.manager import BackendManager
from gtkpass.backends.demo import DemoBackend, DemoBackendSettings
from gtkpass.backends.secretservice import SecretServiceBackend, SecretServiceBackendSettings
from gtkpass.backends.pass_cli import PassBackend, PassBackendSettings
from gtkpass.backends.direct import DirectBackend, DirectBackendSettings
from gtkpass.backends import BackendError


@Gtk.Template(filename="src/gtkpass/ui/blueprints/window.ui")
class GTKPassWindow(Adw.ApplicationWindow):
    """Main application window for GTKPass.

    UI is defined in ui/blueprints/window.blp and compiled to window.ui.

    This window provides the main password manager interface with:
    - A sidebar for the password list
    - A detail pane for viewing selected password
    - Search functionality
    - Add password button
    """

    __gtype_name__ = "GTKPassWindow"

    # Template children
    split_view = Gtk.Template.Child()
    password_list = Gtk.Template.Child()
    search_entry = Gtk.Template.Child()
    placeholder_page = Gtk.Template.Child()

    def __init__(self, **kwargs):
        """Initialize the main window."""
        super().__init__(**kwargs)
        
        # Initialize backend manager and GSettings
        self.backend_manager = BackendManager()
        self.settings = Gio.Settings.new("org.ronny_pfannschmidt.gtkpass")
        
        self._setup_actions()
        self._load_backends()
        self._setup_password_list()

    def _setup_actions(self):
        """Set up window actions."""
        # Add password action
        add_action = Gio.SimpleAction.new("add-password", None)
        add_action.connect("activate", self._on_add_password)
        self.add_action(add_action)
    
    def _load_backends(self):
        """Load backend instances from GSettings."""
        try:
            instances = self.settings.get_value("backend-instances")
            
            for backend_id, backend_type in instances:
                try:
                    settings = self._load_backend_settings(backend_id, backend_type)
                    if settings:
                        backend = self._create_backend(backend_type, settings)
                        if backend:
                            self.backend_manager.add_backend(backend_id, backend)
                except Exception as e:
                    print(f"Failed to load backend {backend_id}: {e}")
        except Exception as e:
            print(f"Error loading backends: {e}")
    
    def _load_backend_settings(self, backend_id: str, backend_type: str):
        """Load settings for a specific backend instance."""
        try:
            path = f"/org/ronny-pfannschmidt/gtkpass/backends/{backend_id}/"
            schema_id = f"org.ronny_pfannschmidt.gtkpass.backend.{backend_type}"
            
            backend_gsettings = Gio.Settings.new_with_path(schema_id, path)
            
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
                    use_git=use_git
                )
            elif backend_type == "direct":
                store_dir = backend_gsettings.get_string("password-store-dir")
                gpg_home = backend_gsettings.get_string("gpg-home")
                return DirectBackendSettings(
                    password_store_dir=Path(store_dir) if store_dir else None,
                    gpg_home=Path(gpg_home) if gpg_home else None
                )
        except Exception as e:
            print(f"Error loading settings for {backend_type} backend {backend_id}: {e}")
        return None
    
    def _create_backend(self, backend_type: str, settings):
        """Create a backend instance from settings."""
        try:
            if backend_type == "demo":
                return DemoBackend.create(settings)
            elif backend_type == "secretservice":
                return SecretServiceBackend.create(settings)
            elif backend_type == "pass":
                return PassBackend.create(settings)
            elif backend_type == "direct":
                return DirectBackend.create(settings)
        except BackendError as e:
            print(f"Backend not available: {e}")
        except Exception as e:
            print(f"Error creating {backend_type} backend: {e}")
        return None

    def _setup_password_list(self):
        """Set up the password list."""
        # Connect selection handler
        self.password_list.connect("row-selected", self._on_password_selected)
        
        # Load passwords from backends
        backends = self.backend_manager.get_all_backends()
        if len(backends) > 0:
            self._load_passwords()
        else:
            # No backends configured - show configuration prompt
            self._show_configuration_prompt()
    
    def _load_passwords(self):
        """Load passwords from all backends and display them."""
        # Clear existing rows
        while True:
            row = self.password_list.get_row_at_index(0)
            if row is None:
                break
            self.password_list.remove(row)
        
        # Load passwords from all backends
        all_passwords = []
        for backend_id, backend in self.backend_manager.get_all_backends().items():
            try:
                passwords = list(backend.list_passwords())
                all_passwords.extend(passwords)
            except Exception as e:
                print(f"Error loading passwords from {backend_id}: {e}")
        
        if len(all_passwords) == 0:
            # Backends loaded but no passwords
            self.placeholder_page.set_title("No Passwords Found")
            self.placeholder_page.set_description(
                "Your password store is empty.\n"
                "Add a password to get started."
            )
            return
        
        # Display passwords in the list
        for password in sorted(all_passwords, key=lambda p: p.name):
            row = Adw.ActionRow(
                title=password.name,
                subtitle=str(password.path),
            )
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.password_name = password.name  # Store for later retrieval
            self.password_list.append(row)

    def _show_configuration_prompt(self):
        """Show configuration prompt in main content area."""
        # Update the status page to show configuration instructions
        self.placeholder_page.set_title("No Backends Configured")
        self.placeholder_page.set_description(
            "GTKPass needs a password backend to work.\n"
            "Choose a backend in Preferences to get started."
        )
        self.placeholder_page.set_icon_name("preferences-system-symbolic")
        
        # Add a button to the status page
        prefs_button = Gtk.Button(label="Open Preferences")
        prefs_button.add_css_class("suggested-action")
        prefs_button.add_css_class("pill")
        prefs_button.set_action_name("app.preferences")
        self.placeholder_page.set_child(prefs_button)

    def _on_add_password(self, action, param):
        """Handle add password button click."""
        # Placeholder - will be implemented in future
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Add Password",
            body="Password creation UI will be implemented in the next phase.",
        )
        dialog.add_response("ok", "OK")
        dialog.present()

    def _on_password_selected(self, listbox, row):
        """Handle password selection from the list."""
        if row is None:
            return

        # Placeholder - will show actual password details in future
        # For now, just demonstrate the interaction
        # This is where we would show the detail view
        pass
