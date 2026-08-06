"""Detail pane showing one decrypted password entry."""

import importlib.resources
from typing import ClassVar

from gtkpass._gi import Adw, GObject, Gtk
from gtkpass.backends import PasswordEntry

#: Metadata keys that mean "the account name", in order of preference. Stores
#: written by different tools disagree about which to use.
USERNAME_KEYS = ("username", "user", "login")

#: Likewise for the site a password belongs to.
URL_KEYS = ("url", "website", "uri")

PLACEHOLDER = "—"


@Gtk.Template(
    filename=str(
        importlib.resources.files("gtkpass.ui.blueprints") / "password_detail.ui"
    )
)
class PasswordDetailView(Gtk.Box):
    """Shows a password entry, and asks to have its fields copied.

    The widget does not touch the clipboard itself: it emits copy-requested and
    lets the window apply the user's clipboard timeout and show a toast.
    """

    __gtype_name__ = "PasswordDetailView"

    __gsignals__: ClassVar[dict] = {
        # (field label, value)
        "copy-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    stack: Gtk.Stack = Gtk.Template.Child()
    spinner: Gtk.Spinner = Gtk.Template.Child()
    spinner_label: Gtk.Label = Gtk.Template.Child()
    name_row: Adw.ActionRow = Gtk.Template.Child()
    username_row: Adw.ActionRow = Gtk.Template.Child()
    password_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    url_row: Adw.ActionRow = Gtk.Template.Child()
    notes_group: Adw.PreferencesGroup = Gtk.Template.Child()
    notes_label: Gtk.Label = Gtk.Template.Child()
    copy_username_btn: Gtk.Button = Gtk.Template.Child()
    copy_password_btn: Gtk.Button = Gtk.Template.Child()
    copy_url_btn: Gtk.Button = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entry: PasswordEntry | None = None
        self.stack.set_visible_child_name("content")

    # -- state ---------------------------------------------------------------

    @property
    def entry(self) -> PasswordEntry | None:
        """The entry on display, for whoever needs to act on it."""
        return self._entry

    def show_loading(self, name: str = "") -> None:
        """Show the spinner while an entry is being decrypted."""
        self.spinner_label.set_text(f"Decrypting {name}…" if name else "Decrypting…")
        self.spinner.set_spinning(True)
        self.stack.set_visible_child_name("loading")

    def show_entry(self, entry: PasswordEntry) -> None:
        """Display a decrypted entry."""
        self._replace_entry(entry)

        metadata = entry.metadata
        self.name_row.set_subtitle(entry.name)
        self.username_row.set_subtitle(_first(metadata, USERNAME_KEYS) or PLACEHOLDER)
        self.password_row.set_text(entry.password or "")
        self.url_row.set_subtitle(_first(metadata, URL_KEYS) or PLACEHOLDER)

        notes = _notes(entry)
        self.notes_label.set_text(notes)
        self.notes_group.set_visible(bool(notes))

        self.spinner.set_spinning(False)
        self.stack.set_visible_child_name("content")

    def clear(self) -> None:
        """Forget the entry and blank the rows."""
        self._replace_entry(None)
        self.name_row.set_subtitle("")
        self.username_row.set_subtitle(PLACEHOLDER)
        self.password_row.set_text("")
        self.url_row.set_subtitle(PLACEHOLDER)
        self.notes_label.set_text("")
        self.notes_group.set_visible(False)
        self.spinner.set_spinning(False)

    def set_reveal_password(self, reveal: bool) -> None:
        """Whether the password starts visible rather than dotted out."""
        self.password_row.set_show_password(reveal)

    def _replace_entry(self, entry: PasswordEntry | None) -> None:
        """Drop the previous entry's plaintext before taking a new one."""
        if self._entry is not None:
            self._entry.clear_password()
        self._entry = entry

    # -- copy buttons --------------------------------------------------------

    @Gtk.Template.Callback()
    def _on_copy_username(self, _button) -> None:
        self._request_copy("Username", self.username_row.get_subtitle())

    @Gtk.Template.Callback()
    def _on_copy_password(self, _button) -> None:
        self._request_copy("Password", self.password_row.get_text())

    @Gtk.Template.Callback()
    def _on_copy_url(self, _button) -> None:
        self._request_copy("URL", self.url_row.get_subtitle())

    def _request_copy(self, field: str, value: str | None) -> None:
        if value and value != PLACEHOLDER:
            self.emit("copy-requested", field, value)


def _first(metadata: dict[str, str], keys: tuple[str, ...]) -> str:
    """First non-empty value among ``keys``."""
    for key in keys:
        value = metadata.get(key)
        if value:
            return value
    return ""


def _notes(entry: PasswordEntry) -> str:
    """Notes, however the store happens to record them.

    Both spellings are common: an explicit ``notes:`` key, as pass templates and
    the demo data use, and plain prose on its own lines.
    """
    if not entry.content:
        return ""

    parts = []
    keyed = entry.metadata.get("notes")
    if keyed:
        parts.append(keyed)
    parts.extend(
        line.strip()
        for line in entry.content.split("\n")[1:]
        if line.strip() and ":" not in line
    )
    return "\n".join(parts).strip()
