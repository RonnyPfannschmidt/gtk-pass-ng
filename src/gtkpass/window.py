"""Main application window."""

import importlib.resources
import logging
from pathlib import Path

from gtkpass._gi import Adw, Gio, Gtk
from gtkpass.backends import (
    BackendError,
    PasswordBackend,
    SyncNotPermitted,
    SyncUnavailable,
)
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
    sync_button = Gtk.Template.Child()
    sync_stack = Gtk.Template.Child()

    def __init__(self, **kwargs):
        """Initialize the main window."""
        super().__init__(**kwargs)

        # Initialize backend manager and GSettings
        self.backend_manager = BackendManager()
        self.settings = get_settings()
        # (instance id, backend type, what went wrong)
        self.failed_backends: list[tuple[str, str, str]] = []
        self.backend_types: dict[str, str] = {}  # instance id -> backend type
        # Kept alive deliberately: a Gio.Settings that gets collected stops
        # emitting, and these are what tell us a backend was renamed.
        self._backend_settings: dict[str, Gio.Settings] = {}
        # Bumped per selection so a slow decrypt cannot overwrite a newer one.
        self._detail_request = 0
        # (backend id, name) of the entry on display, or None.
        self._shown: tuple[str, str] | None = None
        self._clipboard = ClipboardCopier(self)
        # Backends whose stores have a remote, refreshed whenever they load.
        self._syncable_backends: list[str] = []
        self._pending_syncs: list[str] = []
        # Bumped per load, so a superseded one cannot deliver into the window
        # it no longer describes. Both run on the pool, and the settings dialog
        # can start a second before the first has come back.
        self._backend_request = 0
        self._listing_request = 0
        # Listings still outstanding, and whether any of them found an entry.
        # The empty-store placeholder can only be decided once they are all in.
        self._pending_listings = 0
        self._listed_anything = False

        # Monitor backend-instances for changes
        self.settings.connect("changed::backend-instances", self._on_backends_changed)

        self._setup_actions()
        self._setup_password_list()
        self._refresh_sync_action()
        self._load_backends()

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

        # Nothing is syncable until the backends have loaded and reported what
        # their stores are, so this starts closed and _refresh_sync_action
        # opens it.
        sync_action = Gio.SimpleAction.new("sync", None)
        sync_action.connect("activate", self._on_sync)
        sync_action.set_enabled(False)
        self.add_action(sync_action)

    def _load_backends(self):
        """Read the configuration here, build the backends on a worker.

        Building one is neither cheap nor bounded. GitStore.probe runs three git
        commands per store; the Secret Service backend opens a D-Bus connection,
        waits up to five seconds for an answer and may then unlock a collection,
        which prompts. All of that used to happen inside __init__, so the window
        did not appear until every configured backend had finished answering --
        and for a store on a mount that had gone away, it never did.

        GSettings is read on this thread, before the worker starts. Those keys
        are a dconf lookup rather than I/O, and keeping every GSettings access
        on the thread that owns the change handlers is worth more than moving
        it.
        """
        self._backend_request += 1
        request = self._backend_request
        self.failed_backends = []

        specs = []
        for backend_id, backend_type in self._configured_instances():
            self.backend_types[backend_id] = backend_type
            self._watch_display_name(backend_id, backend_type)
            settings = self._load_backend_settings(backend_id, backend_type)
            if settings is None:
                logger.error(f"Failed to load settings for backend: {backend_id}")
                self.failed_backends.append(
                    (backend_id, backend_type, "Failed to load settings")
                )
                continue
            specs.append((backend_id, backend_type, settings))

        if not specs:
            logger.info("No backends to load")
            self._backends_ready(request, [])
            return

        logger.info(f"Loading {len(specs)} backend(s)...")
        future = self.backend_manager.submit(self._build_backends, specs)
        on_ui_thread(
            future,
            lambda built: self._backends_ready(request, built),
            lambda error: self._backends_failed(request, error),
        )

    def _configured_instances(self) -> list[tuple[str, str]]:
        """The (id, type) pairs recorded in GSettings, or none if unreadable."""
        try:
            return [
                (str(i), str(t))
                for i, t in self.settings.get_value("backend-instances")
            ]
        except Exception as e:
            logger.exception(f"Error reading the configured backends: {e}")
            return []

    def _build_backends(
        self, specs: list[tuple[str, str, object]]
    ) -> list[tuple[str, str, PasswordBackend | None, str]]:
        """Construct every configured backend. Runs on a worker thread.

        Touches no widget and no GSettings: what it returns reaches the window
        through _backends_ready, on the UI thread. A backend that will not build
        is carried back as its message rather than raised, so one bad store does
        not cost the others.
        """
        built: list[tuple[str, str, PasswordBackend | None, str]] = []
        for backend_id, backend_type, settings in specs:
            logger.debug(f"Loading backend: {backend_id} ({backend_type})")
            try:
                backend = self._create_backend(backend_type, settings)
            except Exception as e:
                logger.exception(f"Exception loading backend {backend_id}: {e}")
                built.append((backend_id, backend_type, None, str(e)))
            else:
                built.append((backend_id, backend_type, backend, ""))
        return built

    def _backends_ready(
        self,
        request: int,
        built: list[tuple[str, str, PasswordBackend | None, str]],
    ) -> None:
        """Install what the worker built, unless a newer load has replaced it."""
        if request != self._backend_request:
            # The configuration changed while this was in flight, and what it
            # holds was built against a manager that has since been shut down.
            logger.debug("Discarding a superseded backend load")
            return

        for backend_id, backend_type, backend, error in built:
            if backend is None:
                self.failed_backends.append((backend_id, backend_type, error))
            else:
                self.backend_manager.add_backend(backend_id, backend)
                logger.info(f"Successfully loaded backend: {backend_id}")

        self._refresh_sync_action()
        self._show_backend_errors()
        self._load_passwords()

    def _backends_failed(self, request: int, error: BaseException) -> None:
        """The build itself fell over, rather than one backend in it."""
        if request != self._backend_request:
            return
        logger.error(f"Error loading backends: {error}")
        self._load_passwords()

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

        # Anything the old manager still has in flight belongs to backends that
        # no longer exist; bumping the listing here drops it on arrival rather
        # than letting it append to the tree the new load is about to build.
        self._listing_request += 1
        self.password_list.clear_all()
        self._refresh_sync_action()

        # Reload backends. The listing follows once they are built.
        self._load_backends()

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
        """Create a backend instance from settings.

        Raises rather than returning None on a BackendError. The message is the
        only thing that tells a blocked store apart from a missing .gpg-id or a
        GPG that would not start, and swallowing it here is why every one of
        them reached the sidebar as the same "Backend not available".
        """
        if backend_type == "demo":
            return DemoBackend.create(settings)
        elif backend_type == "secretservice":
            return SecretServiceBackend.create(settings)
        elif backend_type == "pass":
            return PassBackend.create(settings)
        elif backend_type == "direct":
            return DirectBackend.create(settings)
        raise BackendError(f"Unknown backend type '{backend_type}'")

    def _setup_password_list(self):
        """Set up the password list."""
        # Connect selection handler
        self.password_list.connect_password_selected(self._on_password_selected)
        self.password_detail.connect("copy-requested", self._on_copy_requested)

        # Not a Gio.Settings.bind: Adw.PasswordEntryRow has no property to bind
        # to, and binding a name it does not have logs a GLib-GIO-CRITICAL on
        # every window and does nothing.
        self.settings.connect(
            "changed::show-hidden-passwords", self._apply_reveal_preference
        )
        self._apply_reveal_preference()

    def _load_passwords(self):
        """Rebuild the sidebar, asking each backend for its entries off the UI thread.

        Listing walks a store's whole directory tree, or goes out over D-Bus, so
        it belongs on the pool with every other backend call. The rows arrive
        per backend as each one answers rather than all together, which is why
        the empty-store placeholder waits for the last of them.
        """
        self._listing_request += 1
        request = self._listing_request

        # Clear existing tree
        self.password_list.clear_all()

        # Get all backends (loaded and failed)
        loaded_backends = self.backend_manager.get_all_backends()

        # Check if we have any backends configured
        if len(loaded_backends) == 0 and len(self.failed_backends) == 0:
            # No backends configured - show configuration prompt
            self._show_configuration_prompt()
            return

        self._pending_listings = len(loaded_backends)
        self._listed_anything = False

        # Add each loaded backend as a root node
        for backend_id in loaded_backends:
            backend_node = self.password_list.add_backend(
                backend_id=backend_id,
                backend_name=self._get_backend_display_name(backend_id),
                # Green checkmark for an available, healthy backend.
                icon_name="emblem-default-symbolic",
            )
            self._list_into(request, backend_id, backend_node)

        # Add failed backends with error icon
        for backend_id, _backend_type, _error in self.failed_backends:
            display_name = self._get_backend_display_name(backend_id)
            self.password_list.add_backend(
                backend_id=backend_id,
                backend_name=f"{display_name} (unavailable)",
                icon_name="dialog-error-symbolic",
            )

        # The backend rows exist; their entries append to a model the tree is
        # already watching, so expanding does not have to wait for them.
        self.password_list.expand_first_level()

    def _list_into(self, request: int, backend_id: str, node) -> None:
        """Fill one backend's row in, when its listing comes back."""

        def show(passwords):
            if request != self._listing_request:
                return
            logger.debug(f"Loaded {len(passwords)} passwords from {backend_id}")
            for password in sorted(passwords, key=lambda p: p.name):
                self.password_list.add_password(node, password.name)
            self._listing_answered(request, listed=bool(passwords))

        def report(error):
            if request != self._listing_request:
                return
            logger.error(f"Error loading passwords from {backend_id}: {error}")
            self._listing_answered(request, listed=False)

        try:
            future = self.backend_manager.list_passwords_async(backend_id)
        except ValueError as e:
            report(e)
            return
        on_ui_thread(future, show, report)

    def _listing_answered(self, request: int, listed: bool) -> None:
        """Count one backend in, and decide the placeholder once all have answered."""
        if request != self._listing_request:
            return

        self._listed_anything = self._listed_anything or listed
        self._pending_listings -= 1
        if self._pending_listings > 0 or self._listed_anything:
            return

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

        toast = Adw.Toast.new(message)
        toast.set_timeout(5)
        # This add_toast was missing, so a backend that failed to load said so
        # only in the log. The sidebar row was the sole indication, and it did
        # not carry the reason.
        self.toast_overlay.add_toast(toast)

        logger.warning(f"Failed backends: {message}")
        for backend_id, backend_type, error in self.failed_backends:
            logger.warning(f"  - {backend_id} ({backend_type}): {error}")

    # -- syncing -------------------------------------------------------------

    def _refresh_sync_action(self) -> None:
        """Offer sync only where a backend has a store with a remote.

        The tooltip carries the reason when it is refused, because "the button
        is grey" is not an answer to "why can I not sync?".
        """
        capabilities = self.backend_manager.sync_capabilities()
        syncable = [
            backend_id
            for backend_id, capability in capabilities.items()
            if capability.supported
        ]
        self._syncable_backends = syncable

        action = self.lookup_action("sync")
        if action is not None:
            action.set_enabled(bool(syncable))

        if syncable:
            details = ", ".join(
                capabilities[backend_id].detail for backend_id in syncable
            )
            self.sync_button.set_tooltip_text(details)
        elif capabilities:
            # Whichever reason is most actionable: a store that is a repository
            # without a remote is closer to working than one that is not a
            # repository at all.
            reasons = [
                capability.detail
                for capability in capabilities.values()
                if capability.reason is not SyncUnavailable.NO_STORE
            ]
            self.sync_button.set_tooltip_text(
                reasons[0] if reasons else "No store here can be synced."
            )
        else:
            self.sync_button.set_tooltip_text("No backends are configured.")

    def _on_sync(self, action, param):
        """Pull and push the syncable backends, off the UI thread."""
        if not self._syncable_backends:
            return

        action.set_enabled(False)
        self.sync_stack.set_visible_child_name("busy")

        # One at a time: they queue on the same four-worker pool anyway, and a
        # single report reads better than one toast per backend.
        self._pending_syncs = list(self._syncable_backends)
        self._sync_next()

    def _sync_next(self) -> None:
        if not self._pending_syncs:
            self._sync_finished()
            return

        backend_id = self._pending_syncs.pop(0)

        def done(result):
            if result.pulled or result.pushed:
                self._toast(
                    f"Synced {self._get_backend_display_name(backend_id)}: "
                    f"{result.pulled} in, {result.pushed} out"
                )
            else:
                self._toast(
                    f"{self._get_backend_display_name(backend_id)} is up to date"
                )
            self._sync_next()

        def report(error):
            logger.error("Sync failed for %s: %s", backend_id, error)
            if isinstance(error, SyncNotPermitted):
                self._show_sync_blocked(error)
            else:
                self._toast(f"Could not sync: {error}")
            self._sync_next()

        try:
            future = self.backend_manager.sync_async(backend_id)
        except ValueError as e:
            report(e)
            return
        on_ui_thread(future, done, report)

    def _sync_finished(self) -> None:
        self.sync_stack.set_visible_child_name("idle")
        self._refresh_sync_action()
        # A pull can have brought entries in, so the tree is out of date.
        self._load_passwords()

    def _show_sync_blocked(self, error: "SyncNotPermitted") -> None:
        """Explain the missing sandbox permission and how to grant it."""
        builder = Gtk.Builder.new_from_file(
            str(importlib.resources.files("gtkpass.ui.blueprints") / "sync_blocked.ui")
        )
        dialog = builder.get_object("sync_blocked_dialog")
        builder.get_object("override_command_label").set_label(error.override_command)

        def responded(_dialog, response):
            if response == "copy":
                # No timeout: this is a shell command, not a secret.
                self._clipboard.copy(error.override_command, 0)
                self._toast("Command copied")

        dialog.connect("response", responded)
        dialog.present(self)

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

    def _apply_reveal_preference(self, *_args) -> None:
        """Show or dot out passwords, following the preference."""
        self.password_detail.set_reveal_password(
            self.settings.get_boolean("show-hidden-passwords")
        )

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
