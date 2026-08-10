"""Detail pane showing one decrypted password entry."""

import importlib.resources
from typing import ClassVar

from gtkpass._gi import Adw, Gio, GObject, Gtk
from gtkpass.backends import PasswordEntry

#: Metadata keys that mean "the account name", in order of preference. Stores
#: written by different tools disagree about which to use.
USERNAME_KEYS = ("username", "user", "login")

#: Likewise for the site a password belongs to.
URL_KEYS = ("url", "website", "uri")

#: Keys the pane has a row of its own for. Everything else is shown as it was
#: written rather than dropped: a store carries whatever its owner put there.
KNOWN_KEYS = frozenset(USERNAME_KEYS + URL_KEYS + ("notes",))

#: Keys whose value is a secret in its own right.
#:
#: The first line is not the only one worth hiding. An ``otpauth://`` line is the
#: shared secret every future code comes from; a PIN or a recovery code is a
#: password by another name. All of them used to be plain labels the moment an
#: entry was selected, while the password above them was dotted out.
#:
#: A list of keys rather than a guess at the value: it is predictable, and a
#: field nobody thought of stays visible rather than a hostname being hidden.
SENSITIVE_KEYS = frozenset(
    {
        "otp",
        "otpauth",
        "totp",
        "pin",
        "secret",
        "token",
        "key",
        "seed",
        "recovery",
        "recovery-codes",
        "passphrase",
        "password",
        "api-key",
        "apikey",
    }
)

PLACEHOLDER = "—"

#: What a masked field shows instead of itself.
DOTS = "••••••••"


def looks_sensitive(key: str) -> bool:
    """Whether a field's name says its value is a secret."""
    return key.strip().lower() in SENSITIVE_KEYS


class MetadataField(GObject.Object):
    """One key and value the pane has no dedicated row for.

    The row template in ``password_detail.blp`` binds to these properties by
    name, so the GType name here has to stay in step with the
    ``$GTKPassMetadataField`` casts over there.
    """

    __gtype_name__ = "GTKPassMetadataField"

    key = GObject.Property(type=str, default="")
    value = GObject.Property(type=str, default="")
    sensitive = GObject.Property(type=bool, default=False)

    def __init__(self, key: str = "", value: str = "") -> None:
        super().__init__(key=key, value=value, sensitive=looks_sensitive(key))
        self._revealed = False

    @GObject.Property(type=str, default="")
    def display(self) -> str:
        """What the row shows: the value, or dots while it is hidden."""
        if self.sensitive and not self._revealed:
            return DOTS
        return self.value

    def reveal(self, revealed: bool) -> None:
        """Show or hide this field's value.

        Notifying ``display`` is what redraws the row: the template binds that
        property, and nothing else about the object has changed.
        """
        if self._revealed == revealed:
            return
        self._revealed = revealed
        self.notify("display")


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
    title_label: Gtk.Label = Gtk.Template.Child()
    path_label: Gtk.Label = Gtk.Template.Child()
    username_row: Adw.ActionRow = Gtk.Template.Child()
    password_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    url_row: Adw.ActionRow = Gtk.Template.Child()
    extras_group: Adw.PreferencesGroup = Gtk.Template.Child()
    extras_view: Gtk.ListView = Gtk.Template.Child()
    notes_group: Adw.PreferencesGroup = Gtk.Template.Child()
    notes_label: Gtk.Label = Gtk.Template.Child()
    reveal_extras_button: Gtk.ToggleButton = Gtk.Template.Child()
    copy_username_btn: Gtk.Button = Gtk.Template.Child()
    copy_password_btn: Gtk.Button = Gtk.Template.Child()
    copy_url_btn: Gtk.Button = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entry: PasswordEntry | None = None
        #: Whether passwords are shown rather than dotted out. Kept so that
        #: moving to another entry does not silently re-hide one.
        self._reveal_password = False
        #: Whether the fields that are secrets are shown. Reset per entry: a
        #: reveal is about the entry on screen, not a mode the pane is left in.
        self._reveal_extras = False
        #: Fields with no row of their own, in the order the store wrote them.
        self.extra_fields: Gio.ListStore = Gio.ListStore(item_type=MetadataField)
        self.extras_view.set_model(Gtk.NoSelection(model=self.extra_fields))
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
        self._show_heading(entry.name)
        self.username_row.set_subtitle(_first(metadata, USERNAME_KEYS) or PLACEHOLDER)
        self.password_row.set_text(entry.password or "")
        # Re-applied per entry: setting the text can reset the delegate.
        self.set_reveal_password(self._reveal_password)
        self.url_row.set_subtitle(_first(metadata, URL_KEYS) or PLACEHOLDER)
        self._show_extra_fields(metadata)

        notes = _notes(entry)
        self.notes_label.set_text(notes)
        self.notes_group.set_visible(bool(notes))

        self.spinner.set_spinning(False)
        self.stack.set_visible_child_name("content")

    def _show_heading(self, name: str) -> None:
        """Split ``work/mail`` into the folder that leads to it and the entry.

        The two labels share a line, so the folder keeps the separator and the
        heading reads as the path it is. A top-level entry hides the folder
        label rather than showing an empty one, which would otherwise indent
        the entry by a stray space.
        """
        folder, separator, leaf = name.rpartition("/")
        self.title_label.set_text(leaf)
        self.path_label.set_text(folder + separator)
        self.path_label.set_visible(bool(folder))

    def _show_extra_fields(self, metadata: dict[str, str]) -> None:
        """List every field that has no row of its own, as the store wrote it.

        Dropping them was silent: a line like ``host: db.example.com`` is read
        as metadata, so it never reached the notes either, and an entry could
        lose half of what it carried without saying so.
        """
        self.extra_fields.remove_all()
        for key, value in metadata.items():
            if key not in KNOWN_KEYS and value:
                self.extra_fields.append(MetadataField(key=key, value=value))
        hidden = any(
            self.extra_fields.get_item(index).sensitive
            for index in range(self.extra_fields.get_n_items())
        )
        self.reveal_extras_button.set_visible(hidden)
        # Follows the same preference the password row does: somebody who asked
        # for passwords to be shown did not mean "except these".
        self.set_reveal_extras(self._reveal_password if hidden else False)
        self.extras_group.set_visible(bool(self.extra_fields.get_n_items()))

    def set_reveal_extras(self, reveal: bool) -> None:
        """Show or hide every field that is a secret in its own right."""
        self._reveal_extras = reveal
        if self.reveal_extras_button.get_active() != reveal:
            self.reveal_extras_button.set_active(reveal)
        for index in range(self.extra_fields.get_n_items()):
            self.extra_fields.get_item(index).reveal(reveal)

    @Gtk.Template.Callback()
    def _on_reveal_extras_toggled(self, button) -> None:
        self.set_reveal_extras(button.get_active())

    def clear(self) -> None:
        """Forget the entry and blank the rows."""
        self._replace_entry(None)
        self._show_heading("")
        self.username_row.set_subtitle(PLACEHOLDER)
        self.password_row.set_text("")
        self.url_row.set_subtitle(PLACEHOLDER)
        self._show_extra_fields({})
        self.notes_label.set_text("")
        self.notes_group.set_visible(False)
        self.spinner.set_spinning(False)

    def set_reveal_password(self, reveal: bool) -> None:
        """Whether the password is shown rather than dotted out.

        Adw.PasswordEntryRow has no property for this -- binding one logged a
        GLib-GIO-CRITICAL on every window and changed nothing. Visibility
        belongs to the GtkText the row delegates its editing to, which
        GtkEditable exposes.
        """
        delegate = self.password_row.get_delegate()
        if delegate is not None:
            delegate.set_visibility(reveal)
        self._reveal_password = reveal

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
