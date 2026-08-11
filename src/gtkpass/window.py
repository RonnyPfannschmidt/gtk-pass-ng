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
from gtkpass.backends.recipients import describe
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
from gtkpass.ui.password_add import PasswordAddDialog
from gtkpass.ui.password_detail import (  # noqa: F401
    URL_KEYS,
    USERNAME_KEYS,
    PasswordDetailView,
)
from gtkpass.ui.password_edit import PasswordEditDialog
from gtkpass.ui.password_list import PasswordTreeView  # noqa: F401
from gtkpass.utils.async_ui import on_ui_thread
from gtkpass.utils.clipboard import ClipboardCopier

logger = logging.getLogger(__name__)

#: What the content pane shows when it is not showing an entry, by state name.
#:
#: One status page serves all of these, and it used to be written over in place
#: from three different methods with no record of which situation it was in --
#: so whatever it had last been set to was what the next one showed. A window
#: with a full sidebar and nothing selected still read "Loading...", and an
#: entry that would not decrypt dropped the user onto "No Passwords Found"
#: while its store sat listed beside it.
#:
#: Each entry is (title, description, icon, whether to offer Preferences). A
#: description of None is filled in by the caller, which is how the failure
#: state carries what went wrong.
PLACEHOLDER_STATES: dict[str, tuple[str, str | None, str, bool]] = {
    "loading": ("GTKPass", "Loading...", "dialog-password-symbolic", False),
    "no-backends": (
        "No Backends Configured",
        "GTKPass needs a password backend to work.\n"
        "Choose a backend in Preferences to get started.",
        "preferences-system-symbolic",
        True,
    ),
    "empty": (
        "No Passwords Found",
        "Your password store is empty.\nAdd a password to get started.",
        "dialog-password-symbolic",
        False,
    ),
    "ready": (
        "Nothing Selected",
        "Choose an entry in the sidebar to see it here.",
        "dialog-password-symbolic",
        False,
    ),
    "no-matches": (
        "No Matches",
        "No entry's path contains what you searched for.",
        "system-search-symbolic",
        False,
    ),
    "failed": ("Could Not Open This Entry", None, "dialog-warning-symbolic", False),
}


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
    add_button = Gtk.Template.Child()
    sync_button = Gtk.Template.Child()
    sync_stack = Gtk.Template.Child()
    recipient_banner = Gtk.Template.Child()

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
        # The entry a copied secret came from, so moving off it can take the
        # copy back rather than leaving it there for the timeout to reach.
        self._copied_from: tuple[str, str] | None = None
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
        # Backends whose store no longer matches the recipient set approved for
        # it. Writing to those is refused until somebody has looked.
        self._changed_recipients: list[str] = []
        # Which of PLACEHOLDER_STATES the content pane is currently offering.
        self._placeholder_state = "loading"
        # How many entries the current search matched, so an empty store can be
        # told apart from a search that found nothing.
        self._matched = 0
        # Whether the content pane belongs to an entry: from the moment one is
        # selected, through the decrypt, until it is closed or fails. Not the
        # same as _shown, which is empty for the whole of the decrypt -- and a
        # listing finishing in that window used to pull the pane out from under
        # an entry that was on its way.
        self._showing_entry = False

        # Monitor backend-instances for changes
        self.settings.connect("changed::backend-instances", self._on_backends_changed)

        self._restore_geometry()
        self._setup_actions()
        self._setup_password_list()
        self._setup_search()
        self._refresh_sync_action()
        self._load_backends()

    def _restore_geometry(self):
        """Open at the size the window was last left at.

        Bound rather than read and written by hand: GTK4 keeps default-width and
        default-height in step with the window as it is resized, which is what
        makes this the whole of it. The three keys were in the schema from the
        start with nothing reading them, so the size reset on every launch while
        the settings said otherwise.
        """
        for key, prop in (
            ("window-width", "default-width"),
            ("window-height", "default-height"),
            ("window-maximized", "maximized"),
        ):
            self.settings.bind(key, self, prop, Gio.SettingsBindFlags.DEFAULT)

    def _setup_actions(self):
        """Set up window actions."""
        # Nothing can be added until a backend that can be written to has
        # loaded. The demo store never can be, so this stays closed for it
        # rather than offering a dialog whose save is refused.
        add_action = Gio.SimpleAction.new("add-password", None)
        add_action.connect("activate", self._on_add_password)
        add_action.set_enabled(False)
        self.add_action(add_action)

        # There is nothing to edit until an entry has been decrypted, and the
        # dialog needs its content to fill itself in.
        edit_action = Gio.SimpleAction.new("edit-password", None)
        edit_action.connect("activate", self._on_edit_password)
        edit_action.set_enabled(False)
        self.add_action(edit_action)

        # Likewise nothing to delete, and nowhere to delete it from until a
        # store that can be written to holds it.
        delete_action = Gio.SimpleAction.new("delete-password", None)
        delete_action.connect("activate", self._on_delete_password)
        delete_action.set_enabled(False)
        self.add_action(delete_action)

        # Nothing is syncable until the backends have loaded and reported what
        # their stores are, so this starts closed and _refresh_sync_action
        # opens it.
        sync_action = Gio.SimpleAction.new("sync", None)
        sync_action.connect("activate", self._on_sync)
        sync_action.set_enabled(False)
        self.add_action(sync_action)

        # Building the backends again from the configuration that is already
        # there. What a failed backend needs once whatever stopped it -- an
        # unmounted store, a locked keyring, an agent that had not started --
        # has been dealt with outside the application.
        reload_action = Gio.SimpleAction.new("reload", None)
        reload_action.connect("activate", self._on_reload)
        self.add_action(reload_action)

        # Reaching the search box from the keyboard. Always available: there is
        # nothing to break by focusing an empty one.
        search_action = Gio.SimpleAction.new("search", None)
        search_action.connect("activate", lambda *_: self.search_entry.grab_focus())
        self.add_action(search_action)

        # Copying without reaching for the mouse. Both follow the entry on
        # display, so they are closed for exactly as long as the edit action is.
        for name, field in (
            ("copy-password", "Password"),
            ("copy-username", "Username"),
        ):
            copy_action = Gio.SimpleAction.new(name, None)
            copy_action.connect(
                "activate", lambda _action, _param, field=field: self._copy_field(field)
            )
            copy_action.set_enabled(False)
            self.add_action(copy_action)

        self._install_help_overlay()

    def _install_help_overlay(self) -> None:
        """Give the window its shortcuts window, and with it the action.

        ``set_help_overlay`` is what adds ``win.show-help-overlay``, so this has
        to happen before anything binds an accelerator to that name.
        """
        builder = Gtk.Builder.new_from_file(
            str(importlib.resources.files("gtkpass.ui.blueprints") / "shortcuts.ui")
        )
        overlay = builder.get_object("help_overlay")
        if overlay is not None:
            self.set_help_overlay(overlay)

    def _copy_field(self, field: str) -> None:
        """Copy a field of the selected entry, whether or not the pane has it.

        When the pane holds the entry this goes through the pane rather than
        around it, so the clipboard timeout, the toast and the take-back on
        navigation all apply without being repeated here.

        Otherwise the entry is fetched for the copy alone. That is the case
        whenever the copy is asked for before the decrypt has come back -- a
        right-click both selects a row and puts a menu over it, and the store
        takes as long as it takes -- and reading the pane then would copy an
        empty string or, worse, whatever was on it before.
        """
        selected = self.password_list.get_selected_password()
        if selected is None or selected == self._shown:
            if not self.password_detail.copy_field(field):
                self._toast(f"There is no {field.lower()} to copy")
            return

        backend_id, password_name = selected

        def copy(entry):
            value = _field_of(entry, field)
            entry.clear_password()
            if not value:
                self._toast(f"{password_name} has no {field.lower()}")
                return
            self._on_copy_requested(None, field, value)
            # Recorded against the entry it came from, so moving elsewhere
            # takes it back as it does for a copy made from the pane.
            self._copied_from = selected

        def report(error):
            logger.error(f"Could not read an entry from {backend_id}: {error}")
            self._toast(f"Could not copy from {password_name}: {error}")

        try:
            future = self.backend_manager.get_password_async(backend_id, password_name)
        except ValueError as e:
            report(e)
            return
        on_ui_thread(future, copy, report)

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
        self._refresh_write_actions()
        self._refresh_recipient_banner()
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

    def _on_reload(self, _action, _param) -> None:
        """Build every configured backend again, from scratch.

        The same path a configuration change takes, because it is the same
        work: the manager is replaced and everything is asked again. What
        differs is the reason -- nothing here changed, something out there did.
        """
        logger.info("Reloading the backends on request")
        self._rebuild_backends()
        self._toast("Reloading...")

    def _on_backends_changed(self, settings, key):
        """Handle backend configuration changes.

        Args:
            settings: GSettings instance
            key: Changed key (backend-instances)
        """
        logger.info("Backend configuration changed, reloading...")
        self._rebuild_backends()

    def _rebuild_backends(self) -> None:
        """Throw the manager away and load everything again."""
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
                    approved_recipients=backend_gsettings.get_string(
                        "approved-recipients"
                    ),
                )
            elif backend_type == "direct":
                store_dir = backend_gsettings.get_string("password-store-dir")
                gpg_home = backend_gsettings.get_string("gpg-home")
                return DirectBackendSettings(
                    password_store_dir=Path(store_dir) if store_dir else None,
                    gpg_home=Path(gpg_home) if gpg_home else None,
                    approved_recipients=backend_gsettings.get_string(
                        "approved-recipients"
                    ),
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

    def _refresh_write_actions(self) -> None:
        """Offer adding only where something can take it.

        The tooltip carries the reason when it cannot, because "the button is
        grey" is not an answer to "why can I not add a password?".
        """
        writable = self.backend_manager.writable_backends()
        action = self.lookup_action("add-password")
        if action is not None:
            action.set_enabled(bool(writable))

        # Deleting needs an entry as well as a store that will take the change.
        delete_action = self.lookup_action("delete-password")
        if delete_action is not None:
            delete_action.set_enabled(
                self._shown is not None and self._shown[0] in writable
            )

        if writable:
            self.add_button.set_tooltip_text("Add Password")
        elif self.backend_manager.get_all_backends():
            self.add_button.set_tooltip_text(
                "No configured store can be written to. The demo store is read-only."
            )
        else:
            self.add_button.set_tooltip_text("No backends are configured.")

    def _setup_search(self):
        """Connect the search box to the sidebar.

        It sat there with a placeholder promising search and nothing behind it,
        and Preferences offered a "search as you type" switch over a feature
        that did not exist. Both signals are connected either way and the
        preference decides which one acts: reading it at the moment of the
        keystroke means a change to it takes effect without reopening anything.
        """
        self.search_entry.connect("search-changed", self._on_search_changed)
        # Enter is the other half of the preference, and is also what somebody
        # who has switched typing off will reach for.
        self.search_entry.connect("activate", lambda *_: self._apply_search())
        # Escape in the box clears it rather than leaving the tree narrowed by
        # a search the user has visibly abandoned.
        self.search_entry.connect("stop-search", lambda *_: self._clear_search())

    def _on_search_changed(self, _entry) -> None:
        if self.settings.get_boolean("search-as-you-type"):
            self._apply_search()
        elif not self.search_entry.get_text().strip():
            # Emptying the box is not a search, it is the end of one, and
            # leaving the tree narrowed to a query no longer on screen would
            # look like entries had gone missing.
            self._apply_search()

    def _clear_search(self) -> None:
        self.search_entry.set_text("")
        self._apply_search()

    def _apply_search(self) -> None:
        """Narrow the sidebar to the current query and say what came of it."""
        self._matched = self.password_list.set_filter(self.search_entry.get_text())
        self._refresh_placeholder(reapply=False)

    def _refresh_placeholder(self, reapply: bool = True) -> None:
        """Say what the sidebar currently holds, once it is settled.

        A search that matched nothing is not an empty store: one is the user's
        query and the other is their store, and telling them apart is the whole
        point of saying anything at all.

        ``reapply`` narrows a sidebar that has just been rebuilt. Listings come
        back one backend at a time and go into the tree as they arrive, so a
        search running while they land has to be applied again over the result.
        """
        if self._pending_listings > 0:
            return
        if not self.backend_manager.get_all_backends() and not self.failed_backends:
            # The configuration prompt owns the pane; there is nothing to list.
            return

        if self.search_entry.get_text().strip():
            if reapply:
                self._matched = self.password_list.set_filter(
                    self.search_entry.get_text()
                )
            self._show_placeholder("ready" if self._matched else "no-matches")
        else:
            self._show_placeholder("ready" if self._listed_anything else "empty")

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

        # Add failed backends with error icon, carrying why they failed. The
        # row said "unavailable" and nothing else, so the reason lived only in
        # a toast -- for five seconds, once, at startup.
        for backend_id, backend_type, error in self.failed_backends:
            display_name = self._get_backend_display_name(backend_id)
            self.password_list.add_backend(
                backend_id=backend_id,
                backend_name=f"{display_name} (unavailable)",
                icon_name="dialog-error-symbolic",
                tooltip=f"{backend_type}: {error}",
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
        # Every backend having answered is what settles the pane: an invitation
        # to pick something, or the news that there is nothing to pick. Neither
        # may overwrite an entry already on display -- a sync finishing while
        # one is open re-lists, and the listing is not what the user is looking
        # at.
        self._refresh_placeholder()

    def _get_backend_display_name(self, backend_id: str) -> str:
        """Name to show for a configured backend instance.

        Prefers the name the user typed in the settings dialog, falling back to
        one derived from the backend type.
        """
        backend_type = self.backend_types.get(backend_id, "")
        return get_backend_display_name(backend_type, backend_id)

    def _show_configuration_prompt(self):
        """Show configuration prompt in main content area."""
        self._show_placeholder("no-backends")

    def _show_placeholder(self, state: str, detail: str = "") -> None:
        """Put the content pane into one of PLACEHOLDER_STATES.

        Every situation that has no entry to show goes through here, so the
        page always says which one it is in rather than whatever the last
        caller happened to leave behind.

        An entry already on display is left alone: only the states that mean
        "there is nothing to show" take the pane back from it.
        """
        title, description, icon, offer_preferences = PLACEHOLDER_STATES[state]
        self.placeholder_page.set_title(title)
        self.placeholder_page.set_description(
            detail if description is None else description
        )
        self.placeholder_page.set_icon_name(icon)
        self.open_preferences_button.set_visible(offer_preferences)
        self._placeholder_state = state

        if state in ("no-backends", "empty", "failed") or not self._showing_entry:
            self.content_stack.set_visible_child_name("placeholder")
            self._showing_entry = False

    def _show_backend_errors(self):
        """Say that a backend would not load, and offer to try it again.

        A store on a mount that is not up yet, a GPG agent that had not
        started, a keyring that was locked: every one of those is fixed outside
        the application and then wants retrying. Without this the only way to
        try again was to quit and start over, so the toast carries the retry
        rather than only the news.
        """
        if len(self.failed_backends) == 0:
            return

        if len(self.failed_backends) == 1:
            backend_id, backend_type, error = self.failed_backends[0]
            name = self._get_backend_display_name(backend_id)
            message = f"{name} ({backend_type}) did not load: {error}"
        else:
            message = f"{len(self.failed_backends)} backends did not load"

        toast = Adw.Toast.new(message)
        toast.set_timeout(5)
        toast.set_button_label("Retry")
        toast.set_action_name("win.reload")
        # This add_toast was missing, so a backend that failed to load said so
        # only in the log. The sidebar row was the sole indication, and it did
        # not carry the reason -- it does now, in its tooltip.
        self.toast_overlay.add_toast(toast)

        logger.warning(f"Failed backends: {message}")
        for backend_id, backend_type, error in self.failed_backends:
            logger.warning(f"  - {backend_id} ({backend_type}): {error}")

    # -- recipients ----------------------------------------------------------

    def _refresh_recipient_banner(self) -> None:
        """Say so, and keep saying so, while a store's recipients are unapproved.

        Writing to such a store is refused by the backend; this is what makes
        that visible before somebody runs into it, and what offers the only way
        to lift it.
        """

        def unapproved(backend) -> bool:
            audit = backend.recipient_audit()
            return audit is not None and audit.changed

        self._changed_recipients = [
            backend_id
            for backend_id, backend in self.backend_manager.get_all_backends().items()
            if unapproved(backend)
        ]

        self.recipient_banner.set_revealed(bool(self._changed_recipients))
        if not self._changed_recipients:
            return

        first = self._changed_recipients[0]
        name = self._get_backend_display_name(first)
        if len(self._changed_recipients) > 1:
            title = f"{len(self._changed_recipients)} stores have new recipients"
        else:
            title = f"{name}: who this store is encrypted to has changed"
        self.recipient_banner.set_title(title)

    @Gtk.Template.Callback()
    def _on_review_recipients(self, _banner) -> None:
        self._open_recipients_dialog()

    def _open_recipients_dialog(self):
        """Show what changed, and offer to record it as approved.

        Returns the dialog, as _open_edit_dialog does, so a test can drive it to
        a response rather than only proving it was built.
        """
        if not self._changed_recipients:
            return None
        backend_id = self._changed_recipients[0]
        backend = self.backend_manager.get_backend(backend_id)
        if backend is None:
            return None
        audit = backend.recipient_audit()
        if audit is None:
            return None

        builder = Gtk.Builder.new_from_file(
            str(
                importlib.resources.files("gtkpass.ui.blueprints")
                / "recipients_changed.ui"
            )
        )
        dialog = builder.get_object("recipients_changed_dialog")
        builder.get_object("summary_label").set_label(
            f"{self._get_backend_display_name(backend_id)}: {describe(audit)}"
        )
        builder.get_object("changed_label").set_label(_recipient_lines(audit))

        stale = audit.stale_entries
        builder.get_object("stale_heading").set_visible(bool(stale))
        builder.get_object("stale_scroller").set_visible(bool(stale))
        builder.get_object("stale_label").set_label("\n".join(stale))

        def responded(_dialog, response):
            if response == "accept":
                self._approve_recipients(backend_id, audit.record)

        dialog.connect("response", responded)
        dialog.present(self)
        return dialog

    def _approve_recipients(self, backend_id: str, record: str) -> None:
        """Record a recipient set as the one this store is expected to have.

        Written to the instance's own settings rather than into the store: the
        record is what a later change gets compared against, so it has to live
        where whoever can write to the remote cannot reach it.

        The backends read it when they are built, so this reloads them -- which
        is also what lifts the refusal on writing.
        """
        backend_type = self.backend_types.get(backend_id, "")
        try:
            get_backend_settings(backend_type, backend_id).set_string(
                "approved-recipients", record
            )
        except Exception as e:
            logger.error(f"Could not record the recipients for {backend_id}: {e}")
            self._toast(f"Could not record the recipients: {e}")
            return

        self._toast(
            f"Recipients accepted for {self._get_backend_display_name(backend_id)}"
        )
        self.backend_manager.shutdown()
        self.backend_manager = BackendManager()
        self._listing_request += 1
        self.password_list.clear_all()
        self._load_backends()

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
                # No timeout, and not marked as a secret: this is a shell
                # command to run, and it belongs in the clipboard history.
                self._clipboard.copy(error.override_command, 0, secret=False)
                self._toast("Command copied")

        dialog.connect("response", responded)
        dialog.present(self)

    def _on_add_password(self, action, param):
        """Handle add password button click."""
        self._open_add_dialog()

    def _open_add_dialog(self) -> PasswordAddDialog | None:
        """Offer a new entry in whichever stores can take one.

        Returns the dialog, as the editor does, so a test can drive it to a
        response rather than only prove it was built.

        Returns:
            The dialog, or None when no configured backend can be written to.
        """
        writable = self.backend_manager.writable_backends()
        if not writable:
            # The action is insensitive whenever this is so; reaching here means
            # the shortcut or the menu got there first.
            self._toast("No configured store can be written to.")
            return None

        dialog = PasswordAddDialog()
        dialog.offer(
            backends=[
                (backend_id, self._get_backend_display_name(backend_id))
                for backend_id in writable
            ],
            taken=self.password_list.entry_names(),
            preselect=self._selected_backend(),
            folder=self.password_list.selected_folder(),
        )
        dialog.connect("added", lambda _dialog, *args: self._add_entry(*args))
        dialog.present(self)
        return dialog

    def _selected_backend(self) -> str:
        """The store the sidebar is standing in, if it is standing in one."""
        if self._shown is not None:
            return self._shown[0]
        return self.password_list.selected_backend()

    def _add_entry(self, backend_id: str, name: str, content: str) -> None:
        """Write a new entry, off the UI thread as every other write is."""

        def added(_result):
            self._toast(f"Added {name}")
            # Re-list rather than inserting the row here: the store is what
            # decides whether the entry exists, and a listing is how the rest
            # of the window finds out.
            self._load_passwords()
            self._on_password_selected(backend_id, name)

        def report(error):
            logger.error(f"Could not add an entry to {backend_id}: {error}")
            self._toast(f"Could not add {name}: {error}")

        try:
            future = self.backend_manager.add_password_async(backend_id, name, content)
        except ValueError as e:
            report(e)
            return
        on_ui_thread(future, added, report)

    def _on_password_selected(self, backend_id: str, password_name: str):
        """Decrypt the selected entry and show it in the detail pane.

        Args:
            backend_id: ID of the backend containing the password
            password_name: Name of the selected password
        """
        # The name deliberately does not appear in the log. An entry name says
        # which account somebody holds, the log goes to the journal when the
        # application is launched from the desktop, and -d is exactly the flag
        # somebody turns on when something is wrong. The toasts below carry the
        # name, on screen, where it belongs.
        logger.debug(f"Opening an entry from backend: {backend_id}")

        self._detail_request += 1
        request = self._detail_request

        self._showing_entry = True
        self.content_stack.set_visible_child_name("detail")
        self.password_detail.show_loading(password_name)
        # Before the decrypt returns: a right-click both selects the row and
        # opens the menu over it, and the menu must not be grey for the second
        # or two the store takes to answer.
        self._refresh_copy_actions()

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
            logger.error(f"Could not open an entry from {backend_id}: {error}")
            self.password_detail.clear()
            self._set_shown(None)
            self._showing_entry = False
            # On the page rather than only in a toast: five seconds is not long
            # enough to read a GPG error, and the pane is where the user is
            # already looking.
            self._show_placeholder("failed", f"{password_name}\n\n{error}")

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
        if self._copied_from is not None and shown != self._copied_from:
            # Moving off the entry a secret was copied from ends the reason to
            # keep it. Re-opening the same one does not -- saving an edit
            # re-selects it, and that must not throw the copy away.
            self._clipboard.clear_if_ours()
            self._copied_from = None
        self._shown = shown
        action = self.lookup_action("edit-password")
        if action is not None:
            action.set_enabled(shown is not None)
        self._refresh_copy_actions()
        self._refresh_write_actions()

    def _refresh_copy_actions(self) -> None:
        """Copying follows the selection, not the pane.

        The two are the same once an entry has been opened, and they are not
        while it is still being decrypted -- which is exactly when a context
        menu opened by the right-click that made the selection is on screen.
        """
        selected = (
            self.password_list.get_selected_password() is not None
            or self._shown is not None
        )
        for name in ("copy-password", "copy-username"):
            action = self.lookup_action(name)
            if action is not None:
                action.set_enabled(selected)

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

    def _on_delete_password(self, action, param):
        """Handle the delete action."""
        self._confirm_delete()

    def _confirm_delete(self) -> Adw.AlertDialog | None:
        """Ask before removing the entry on display.

        The one operation that stops to ask. What GTKPass writes to a store it
        can commit, and a commit can be undone -- but a Secret Service item has
        no history at all, and neither has a secret nobody else kept a copy of.

        Returns the dialog, as the other two do, so a test can drive it to a
        response rather than only prove it was built.
        """
        if self._shown is None:
            return None
        backend_id, password_name = self._shown

        builder = Gtk.Builder.new_from_file(
            str(
                importlib.resources.files("gtkpass.ui.blueprints") / "confirm_delete.ui"
            )
        )
        dialog = builder.get_object("confirm_delete_dialog")
        # Named, because "Delete this password?" is a question nobody can
        # answer -- least of all after arrow-keying through a tree.
        dialog.set_body(
            f"{password_name}\n\n"
            f"This removes it from {self._get_backend_display_name(backend_id)}. "
            f"It cannot be undone from here."
        )

        def responded(_dialog, response):
            if response == "delete":
                self._delete_entry(backend_id, password_name)

        dialog.connect("response", responded)
        dialog.present(self)
        return dialog

    def _delete_entry(self, backend_id: str, password_name: str) -> None:
        """Remove an entry, off the UI thread as every other write is."""

        def deleted(_result):
            self._toast(f"Deleted {password_name}")
            # Let go of the pane before re-listing: what it holds no longer
            # exists, and the plaintext it holds has no reason to stay.
            self.password_detail.clear()
            self._set_shown(None)
            self._showing_entry = False
            self._show_placeholder("ready")
            self._load_passwords()

        def report(error):
            logger.error(f"Could not delete an entry from {backend_id}: {error}")
            self._toast(f"Could not delete {password_name}: {error}")

        try:
            future = self.backend_manager.delete_password_async(
                backend_id, password_name
            )
        except ValueError as e:
            report(e)
            return
        on_ui_thread(future, deleted, report)

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
            logger.error(f"Could not save an entry to {backend_id}: {error}")
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
        self._copied_from = self._shown
        if timeout > 0:
            self._toast(f"{field} copied, clearing in {timeout}s")
        else:
            self._toast(f"{field} copied")

    def discard_clipboard(self) -> None:
        """Take a copied secret back before the application goes away.

        Called from GTKPassApp.do_shutdown rather than from a signal here. The
        "destroy" signal is emitted when a window is disposed, not when it is
        told to close: gtk_window_destroy only drops GTK's own reference, and
        this window is still held by the settings handlers and by whatever the
        pool has in flight, so it can outlive the application that owned it.
        A copy left on the clipboard would outlive both.
        """
        self._clipboard.clear_at_shutdown()

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))


def _field_of(entry, field: str) -> str:
    """One of the copyable fields, read straight off a decrypted entry.

    The same keys the detail pane picks its rows out with, so a copy made
    without opening an entry lands on the same value as one made from the pane.
    """
    if field == "Password":
        return entry.password or ""
    keys = {"Username": USERNAME_KEYS, "URL": URL_KEYS}[field]
    metadata = entry.metadata
    for key in keys:
        if metadata.get(key):
            return metadata[key]
    return ""


def _recipient_lines(audit) -> str:
    """The change itself, spelled out for the review dialog."""
    lines = []
    for name in audit.added:
        lines.append(f"+ {name}")
    for name in audit.removed:
        lines.append(f"- {name}")
    for name in audit.unknown_recipients:
        lines.append(f"? {name}  (no key for this recipient here)")
    return "\n".join(lines) or "(the file changed without changing who it names)"
