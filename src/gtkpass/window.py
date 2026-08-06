"""Main application window."""

import importlib.resources
import logging
from pathlib import Path

from gtkpass._gi import Adw, Gio, Gtk
from gtkpass.backends import BackendError
from gtkpass.backends.demo import DemoBackend, DemoBackendSettings
from gtkpass.backends.direct import DirectBackend, DirectBackendSettings
from gtkpass.backends.manager import BackendManager
from gtkpass.backends.pass_cli import PassBackend, PassBackendSettings
from gtkpass.backends.secretservice import (
    SecretServiceBackend,
    SecretServiceBackendSettings,
)
from gtkpass.config import (
    get_backend_display_name,
    get_backend_settings,
    get_settings,
)

# Imported for their side effect: the GTypes must be registered before the
# template below is parsed, or window.ui fails with "Invalid object type".
from gtkpass.ui.password_detail import PasswordDetailView  # noqa: F401
from gtkpass.ui.password_edit import PasswordEditDialog
from gtkpass.ui.password_list import PasswordTreeView  # noqa: F401
from gtkpass.utils.async_ui import on_ui_thread
from gtkpass.utils.clipboard import ClipboardCopier

logger = logging.getLogger(__name__)


@Gtk.Template(
    filename=str(importlib.resources.files("gtkpass.ui.blueprints") / "window.ui")
)
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
    open_preferences_button = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()
    content_stack = Gtk.Template.Child()
    password_detail = Gtk.Template.Child()

    def __init__(self, **kwargs):
        """Initialize the main window."""
        super().__init__(**kwargs)

        # Initialize backend manager and GSettings
        self.backend_manager = BackendManager()
        self.settings = get_settings()
        self.failed_backends = []  # Track backends that failed to load
        self.backend_types: dict[str, str] = {}  # instance id -> backend type
        # Kept alive deliberately: a Gio.Settings that gets collected stops
        # emitting, and these are what tell us a backend was renamed.
        self._backend_settings: dict[str, Gio.Settings] = {}
        # Bumped per selection so a slow decrypt cannot overwrite a newer one.
        self._detail_request = 0
        # (backend id, name) of the entry on display, or None.
        self._shown: tuple[str, str] | None = None
        self._clipboard = ClipboardCopier(self)

        # Monitor backend-instances for changes
        self.settings.connect("changed::backend-instances", self._on_backends_changed)

        self._setup_actions()
        self._load_backends()
        self._setup_password_list()

    def _setup_actions(self):
        """Set up window actions."""
        # Add password action
        add_action = Gio.SimpleAction.new("add-password", None)
        add_action.connect("activate", self._on_add_password)
        self.add_action(add_action)

        # There is nothing to edit until an entry has been decrypted, and the
        # dialog needs its content to fill itself in.
        edit_action = Gio.SimpleAction.new("edit-password", None)
        edit_action.connect("activate", self._on_edit_password)
        edit_action.set_enabled(False)
        self.add_action(edit_action)

    def _load_backends(self):
        """Load backend instances from GSettings."""
        try:
            instances = self.settings.get_value("backend-instances")

            if len(instances) == 0:
                logger.info("No backends configured in GSettings")
                return

            logger.info(f"Loading {len(instances)} backend(s)...")

            for backend_id, backend_type in instances:
                self.backend_types[backend_id] = backend_type
                self._watch_display_name(backend_id, backend_type)
                try:
                    logger.debug(f"Loading backend: {backend_id} ({backend_type})")
                    settings = self._load_backend_settings(backend_id, backend_type)
                    if settings:
                        backend = self._create_backend(backend_type, settings)
                        if backend:
                            self.backend_manager.add_backend(backend_id, backend)
                            logger.info(f"Successfully loaded backend: {backend_id}")
                        else:
                            logger.warning(
                                f"Backend not available: {backend_id} ({backend_type})"
                            )
                            self.failed_backends.append(
                                (backend_id, backend_type, "Backend not available")
                            )
                    else:
                        logger.error(
                            f"Failed to load settings for backend: {backend_id}"
                        )
                        self.failed_backends.append(
                            (backend_id, backend_type, "Failed to load settings")
                        )
                except Exception as e:
                    logger.exception(f"Exception loading backend {backend_id}: {e}")
                    self.failed_backends.append((backend_id, backend_type, str(e)))
        except Exception as e:
            logger.exception(f"Error loading backends: {e}")

    def _watch_display_name(self, backend_id: str, backend_type: str) -> None:
        """Refresh the sidebar when this backend is renamed.

        Renaming writes the instance's own display-name key, so it never
        touches backend-instances and the list would otherwise keep showing
        the old label until the next restart.
        """
        if backend_id in self._backend_settings:
            return
        try:
            backend_gsettings = get_backend_settings(backend_type, backend_id)
        except Exception as e:
            logger.debug(f"Cannot watch {backend_id} for renames: {e}")
            return
        backend_gsettings.connect(
            "changed::display-name", lambda *_: self._load_passwords()
        )
        self._backend_settings[backend_id] = backend_gsettings

    def _on_backends_changed(self, settings, key):
        """Handle backend configuration changes.

        Args:
            settings: GSettings instance
            key: Changed key (backend-instances)
        """
        logger.info("Backend configuration changed, reloading...")

        # Shut the old manager down first; it owns a thread pool, and replacing
        # it without doing so leaks four threads on every settings change.
        self.backend_manager.shutdown()
        self.backend_manager = BackendManager()
        self.failed_backends = []
        self.backend_types = {}
        self._backend_settings = {}

        # Reload backends
        self._load_backends()

        # Refresh the password list
        self._load_passwords()

    def _load_backend_settings(self, backend_id: str, backend_type: str):
        """Load settings for a specific backend instance."""
        try:
            backend_gsettings = get_backend_settings(backend_type, backend_id)

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
            logger.error(
                f"Error loading settings for {backend_type} backend {backend_id}: {e}"
            )
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
            logger.warning(f"Backend not available: {backend_type} - {e}")
        except Exception as e:
            logger.exception(f"Error creating {backend_type} backend: {e}")
        return None

    def _setup_password_list(self):
        """Set up the password list."""
        # Connect selection handler
        self.password_list.connect_password_selected(self._on_password_selected)
        self.password_detail.connect("copy-requested", self._on_copy_requested)
        self.settings.bind(
            "show-hidden-passwords",
            self.password_detail.password_row,
            "show-password",
            Gio.SettingsBindFlags.GET,
        )

        # Show warning for failed backends
        if len(self.failed_backends) > 0:
            self._show_backend_errors()

        # Load passwords from backends
        self._load_passwords()

    def _load_passwords(self):
        """Load passwords from all backends and display them."""
        # Clear existing tree
        self.password_list.clear_all()

        # Get all backends (loaded and failed)
        loaded_backends = self.backend_manager.get_all_backends()

        # Check if we have any backends configured
        if len(loaded_backends) == 0 and len(self.failed_backends) == 0:
            # No backends configured - show configuration prompt
            self._show_configuration_prompt()
            return

        has_any_passwords = False

        # Add each loaded backend as a root node
        for backend_id, backend in loaded_backends.items():
            # Determine icon based on backend type
            # Using green checkmark for available/healthy backends
            icon_name = "emblem-default-symbolic"  # Green checkmark

            # Create friendly display name
            display_name = self._get_backend_display_name(backend_id)

            # Add backend to tree
            backend_node = self.password_list.add_backend(
                backend_id=backend_id, backend_name=display_name, icon_name=icon_name
            )

            # Load passwords from this backend
            try:
                passwords = list(backend.list_passwords())
                logger.debug(f"Loaded {len(passwords)} passwords from {backend_id}")

                if len(passwords) > 0:
                    has_any_passwords = True

                # Add passwords under the backend
                for password in sorted(passwords, key=lambda p: p.name):
                    self.password_list.add_password(backend_node, password.name)
            except Exception as e:
                logger.error(f"Error loading passwords from {backend_id}: {e}")

        # Add failed backends with error icon
        for backend_id, _backend_type, _error in self.failed_backends:
            icon_name = "dialog-error-symbolic"  # Red error icon for unavailable
            display_name = self._get_backend_display_name(backend_id)
            self.password_list.add_backend(
                backend_id=backend_id,
                backend_name=f"{display_name} (unavailable)",
                icon_name=icon_name,
            )

        # Expand all backend nodes
        self.password_list.expand_first_level()

        if not has_any_passwords and len(loaded_backends) > 0:
            # Backends loaded but no passwords
            self.placeholder_page.set_title("No Passwords Found")
            self.placeholder_page.set_description(
                "Your password store is empty.\nAdd a password to get started."
            )
            self.placeholder_page.set_icon_name("dialog-password-symbolic")
            # The configuration prompt reveals this and nothing else hides it.
            self.open_preferences_button.set_visible(False)

    def _get_backend_display_name(self, backend_id: str) -> str:
        """Name to show for a configured backend instance.

        Prefers the name the user typed in the settings dialog, falling back to
        one derived from the backend type.
        """
        backend_type = self.backend_types.get(backend_id, "")
        return get_backend_display_name(backend_type, backend_id)

    def _show_configuration_prompt(self):
        """Show configuration prompt in main content area."""
        # Update the status page to show configuration instructions
        self.placeholder_page.set_title("No Backends Configured")
        self.placeholder_page.set_description(
            "GTKPass needs a password backend to work.\n"
            "Choose a backend in Preferences to get started."
        )
        self.placeholder_page.set_icon_name("preferences-system-symbolic")
        self.open_preferences_button.set_visible(True)

    def _show_backend_errors(self):
        """Show a toast notification for failed backends."""
        if len(self.failed_backends) == 0:
            return

        # Create error message
        if len(self.failed_backends) == 1:
            backend_id, backend_type, error = self.failed_backends[0]
            message = f"Backend '{backend_id}' ({backend_type}) failed: {error}"
        else:
            message = f"{len(self.failed_backends)} backend(s) failed to load"

        # Show toast
        toast = Adw.Toast.new(message)
        toast.set_timeout(5)  # Show for 5 seconds

        # Log the errors
        logger.warning(f"Failed backends: {message}")
        for backend_id, backend_type, error in self.failed_backends:
            logger.warning(f"  - {backend_id} ({backend_type}): {error}")

    def _on_add_password(self, action, param):
        """Handle add password button click."""
        builder = Gtk.Builder.new_from_file(
            str(
                importlib.resources.files("gtkpass.ui.blueprints")
                / "not_implemented.ui"
            )
        )
        builder.get_object("not_implemented_dialog").present(self)

    def _on_password_selected(self, backend_id: str, password_name: str):
        """Decrypt the selected entry and show it in the detail pane.

        Args:
            backend_id: ID of the backend containing the password
            password_name: Name of the selected password
        """
        logger.debug(f"Selected password: {password_name} from backend: {backend_id}")

        self._detail_request += 1
        request = self._detail_request

        self.content_stack.set_visible_child_name("detail")
        self.password_detail.show_loading(password_name)

        def show(entry):
            # Arrow-keying through the tree starts a decrypt per row; without
            # this a slow one landing late would replace a newer selection.
            if request != self._detail_request:
                entry.clear_password()
                return
            self.password_detail.show_entry(entry)
            self._set_shown((backend_id, password_name))

        def report(error):
            if request != self._detail_request:
                return
            logger.error(f"Could not open {password_name}: {error}")
            self.password_detail.clear()
            self.content_stack.set_visible_child_name("placeholder")
            self._set_shown(None)
            self._toast(f"Could not open {password_name}: {error}")

        try:
            future = self.backend_manager.get_password_async(backend_id, password_name)
        except ValueError as e:
            report(e)
            return
        on_ui_thread(future, show, report)

    def _set_shown(self, shown: tuple[str, str] | None) -> None:
        """Record which entry the detail pane holds, and offer editing for it."""
        self._shown = shown
        action = self.lookup_action("edit-password")
        if action is not None:
            action.set_enabled(shown is not None)

    def _on_edit_password(self, action, param):
        """Handle the edit action."""
        self._open_edit_dialog()

    def _open_edit_dialog(self) -> PasswordEditDialog | None:
        """Open the editor on the entry currently on display.

        Returns:
            The dialog, or None when there is nothing to edit.
        """
        entry = self.password_detail.entry
        if self._shown is None or entry is None:
            return None

        backend_id, password_name = self._shown
        dialog = PasswordEditDialog()
        dialog.load(entry)
        dialog.connect(
            "saved",
            lambda _dialog, content: self._save_entry(
                backend_id, password_name, content
            ),
        )
        dialog.present(self)
        return dialog

    def _save_entry(self, backend_id: str, password_name: str, content: str) -> None:
        """Write an edited entry back through its backend.

        Encryption can take a moment and a backend may go out to git, so the
        write happens off the UI thread like the reads do.
        """

        def saved(_result):
            self._toast(f"Saved {password_name}")
            # Read it back rather than trusting the widgets: what the store now
            # holds is the thing worth showing.
            self._on_password_selected(backend_id, password_name)

        def report(error):
            logger.error(f"Could not save {password_name}: {error}")
            self._toast(f"Could not save {password_name}: {error}")

        try:
            future = self.backend_manager.edit_password_async(
                backend_id, password_name, content
            )
        except ValueError as e:
            report(e)
            return
        on_ui_thread(future, saved, report)

    def _on_copy_requested(self, _view, field: str, value: str):
        """Copy a field from the detail pane, clearing it again later."""
        timeout = self.settings.get_int("clipboard-timeout")
        self._clipboard.copy(value, timeout)
        if timeout > 0:
            self._toast(f"{field} copied, clearing in {timeout}s")
        else:
            self._toast(f"{field} copied")

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))
