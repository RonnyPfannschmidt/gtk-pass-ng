"""Detail pane showing one decrypted password entry."""

import importlib.resources
import time
from typing import ClassVar
from urllib.parse import urlparse

from gtkpass._gi import Adw, Gio, GLib, GObject, Gtk
from gtkpass.backends import PasswordEntry, metadata_pair
from gtkpass.otp import (
    OTPError,
    OTPParameters,
    code_at,
    format_code,
    otpauth_line,
    parse_otpauth,
    seconds_remaining,
)


def now() -> float:
    """The wall clock the one-time codes are read against.

    A function of its own so a test can stand still, as ``launch_uri`` is one
    so a test does not open a browser. A code and its countdown are both
    functions of the time, and nothing about them can be asserted while it
    moves underneath.
    """
    return time.time()


#: Schemes an Open button will hand to the desktop.
#:
#: An entry's ``url:`` line is whatever its owner wrote, and a store can be
#: synced from a machine somebody else has written to. ``file://`` and
#: ``smb://`` open something rather than going to a site, and a scheme nobody
#: has thought of is handled by whichever application claimed it. The value is
#: still shown and still selectable -- what is withheld is one click that
#: launches it.
OPENABLE_SCHEMES = frozenset({"http", "https"})


def is_openable(url: str) -> bool:
    """Whether a one-click Open is safe to offer for this value."""
    try:
        return urlparse(url).scheme.lower() in OPENABLE_SCHEMES
    except ValueError:
        return False


def launch_uri(uri: str) -> None:
    """Hand a site to the desktop, through the portal when there is one.

    Gio rather than a browser command: inside the Flatpak this goes to
    org.freedesktop.portal.OpenURI, which needs no host access and no network
    permission of its own. A function of its own so a test can stand in for
    it rather than open a browser.
    """
    Gio.AppInfo.launch_default_for_uri(uri, None)


#: Metadata keys that mean "the account name", in order of preference. Stores
#: written by different tools disagree about which to use.
USERNAME_KEYS = ("username", "user", "login")

#: Likewise for the site a password belongs to.
URL_KEYS = ("url", "website", "uri")


def field_of(entry: PasswordEntry, field: str) -> str:
    """One of the copyable fields, read straight off a decrypted entry.

    Here rather than beside its callers because there are three of them now --
    the window copies a field without opening an entry, the rotation wizard
    shows the username and the site, and this pane picks its own rows out the
    same way. Three copies of "which key means the account name" is three
    chances for a store written by another tool to be read differently in two
    places in the same window.
    """
    if field == "Password":
        return entry.password or ""
    if field == OTP_FIELD:
        return current_code(entry.metadata) or ""
    keys = {"Username": USERNAME_KEYS, "URL": URL_KEYS}[field]
    metadata = entry.metadata
    for key in keys:
        if metadata.get(key):
            return metadata[key]
    return ""


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

#: What the one-time code is called wherever a field is named by a string:
#: the toast, the menu item, the shortcut window and the copy plumbing.
OTP_FIELD = "One-Time Code"

#: Fields that can be copied from outside the pane, named as the copy is
#: reported. The keyboard shortcuts reach all of these.
COPYABLE_FIELDS = ("Password", "Username", "URL", OTP_FIELD)

#: How often the one-time code row redraws, in milliseconds.
#:
#: Twice a second rather than once. The code is recomputed from the clock each
#: tick, so a second-long tick cannot drift -- but it can land just after a
#: rollover and leave the previous code on screen for most of a second, which
#: is a code that will be refused. Half a second costs one HMAC.
OTP_TICK_MS = 500

PLACEHOLDER = "—"

#: What a masked field shows instead of itself.
DOTS = "••••••••"


def current_code(metadata: dict[str, str]) -> str:
    """The code this entry's otpauth line stands for right now, if it has one.

    Empty for an entry with no such line and for one whose line cannot produce
    codes. The pane says which of the two it is; a copy made from the sidebar,
    without the entry being opened, has nothing to say it with and nothing to
    give either.
    """
    line = otpauth_line(metadata)
    if not line:
        return ""
    try:
        return code_at(parse_otpauth(line), now())
    except OTPError:
        return ""


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
    store_label: Gtk.Label = Gtk.Template.Child()
    modified_row: Adw.ActionRow = Gtk.Template.Child()
    username_row: Adw.ActionRow = Gtk.Template.Child()
    password_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    otp_row: Adw.ActionRow = Gtk.Template.Child()
    otp_countdown_label: Gtk.Label = Gtk.Template.Child()
    copy_otp_btn: Gtk.Button = Gtk.Template.Child()
    url_row: Adw.ActionRow = Gtk.Template.Child()
    extras_group: Adw.PreferencesGroup = Gtk.Template.Child()
    extras_view: Gtk.ListView = Gtk.Template.Child()
    notes_group: Adw.PreferencesGroup = Gtk.Template.Child()
    notes_label: Gtk.Label = Gtk.Template.Child()
    reveal_extras_button: Gtk.ToggleButton = Gtk.Template.Child()
    copy_username_btn: Gtk.Button = Gtk.Template.Child()
    copy_password_btn: Gtk.Button = Gtk.Template.Child()
    copy_url_btn: Gtk.Button = Gtk.Template.Child()
    open_url_btn: Gtk.Button = Gtk.Template.Child()

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
        #: The one-time code parameters of the entry on display, and the
        #: GLib source redrawing them. Zero means no timer is running.
        self._otp: OTPParameters | None = None
        self._otp_tick = 0
        # The timer outlives the widget otherwise: GLib holds the callback, the
        # callback holds the view, and the view holds a decrypted secret.
        self.connect("destroy", lambda _view: self._stop_otp())
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

    def show_entry(
        self,
        entry: PasswordEntry,
        store_name: str = "",
        modified: float | None = None,
    ) -> None:
        """Display a decrypted entry.

        Args:
            entry: The entry, with its content loaded.
            store_name: The backend it came from, named under the heading.
            modified: When its file last changed, as a Unix time; zero or
                None for a store that does not say.
        """
        self._replace_entry(entry)

        metadata = entry.metadata
        self._show_heading(entry.name)
        self.store_label.set_text(f"in {store_name}" if store_name else "")
        self.store_label.set_visible(bool(store_name))
        self._show_modified(modified)
        self.username_row.set_subtitle(_first(metadata, USERNAME_KEYS) or PLACEHOLDER)
        self.password_row.set_text(entry.password or "")
        # Re-applied per entry: setting the text can reset the delegate.
        self.set_reveal_password(self._reveal_password)
        self._show_otp(metadata)
        url = _first(metadata, URL_KEYS)
        self.url_row.set_subtitle(url or PLACEHOLDER)
        self.open_url_btn.set_visible(is_openable(url))
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

    def _show_modified(self, modified: float | None) -> None:
        """Say when the entry last changed, in the local time and format."""
        if not modified:
            self.modified_row.set_subtitle("")
            self.modified_row.set_visible(False)
            return
        when = GLib.DateTime.new_from_unix_local(int(modified))
        self.modified_row.set_subtitle(when.format("%x %H:%M") if when else "")
        self.modified_row.set_visible(when is not None)

    # -- one-time codes ------------------------------------------------------

    def _show_otp(self, metadata: dict[str, str]) -> None:
        """Show the code this entry's otpauth line stands for, or why there is none.

        Three outcomes, and the difference between the last two is the point:
        no line at all means no row, while a line that cannot produce codes
        keeps the row and says so. Dropping the row for a malformed line would
        have made a broken entry indistinguishable from an ordinary one.
        """
        self._stop_otp()
        line = otpauth_line(metadata)
        if not line:
            self.otp_row.set_visible(False)
            self.otp_row.set_subtitle("")
            return

        self.otp_row.set_visible(True)
        try:
            self._otp = parse_otpauth(line)
        except OTPError as error:
            self._otp = None
            self.otp_row.set_subtitle(str(error))
            self.otp_countdown_label.set_text("")
            self.copy_otp_btn.set_visible(False)
            return

        self.copy_otp_btn.set_visible(True)
        self.refresh_otp()
        self._otp_tick = GLib.timeout_add(OTP_TICK_MS, self._on_otp_tick)

    def refresh_otp(self) -> None:
        """Put the code valid now, and its remaining life, into the row."""
        if self._otp is None:
            return
        when = now()
        self.otp_row.set_subtitle(format_code(code_at(self._otp, when)))
        self.otp_countdown_label.set_text(f"{seconds_remaining(self._otp, when)}s")

    def _on_otp_tick(self) -> bool:
        self.refresh_otp()
        return GLib.SOURCE_CONTINUE

    def _stop_otp(self) -> None:
        """Forget the secret and stop redrawing it."""
        if self._otp_tick:
            GLib.source_remove(self._otp_tick)
            self._otp_tick = 0
        self._otp = None

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
        self.store_label.set_text("")
        self.store_label.set_visible(False)
        self._show_modified(None)
        self.username_row.set_subtitle(PLACEHOLDER)
        self.password_row.set_text("")
        self._show_otp({})
        self.url_row.set_subtitle(PLACEHOLDER)
        self.open_url_btn.set_visible(False)
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

    @Gtk.Template.Callback()
    def _on_copy_otp(self, _button) -> None:
        self._request_copy(OTP_FIELD, self._current_code())

    @Gtk.Template.Callback()
    def _on_open_url(self, _button) -> None:
        url = self.url_row.get_subtitle() or ""
        if is_openable(url):
            launch_uri(url)

    def copy_field(self, field: str) -> bool:
        """Copy one of COPYABLE_FIELDS, exactly as its own button would.

        What the keyboard shortcuts and the sidebar's menu go through, so the
        clipboard timeout and the take-back on navigation apply to those
        without any of it being written out a second time.

        Returns:
            Whether there was anything to copy. A field the entry does not have
            is not an error, but it is not nothing either: the caller says so,
            rather than leaving a keystroke that did nothing at all.
        """
        getter = {
            "Password": self.password_row.get_text,
            "Username": self.username_row.get_subtitle,
            "URL": self.url_row.get_subtitle,
            OTP_FIELD: self._current_code,
        }[field]
        value = getter()
        self._request_copy(field, value)
        return bool(value) and value != PLACEHOLDER

    def _current_code(self) -> str:
        """The code as of this moment, not as the row last drew it.

        Read from the clock rather than off the row for two reasons: the row
        shows the code in groups and a form wants the digits, and a copy made
        in the half second after a rollover has to be the new code rather than
        the one still on screen.
        """
        return code_at(self._otp, now()) if self._otp is not None else ""

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

    Prose is whatever :func:`metadata_pair` does not claim as a field, which is
    what keeps the two halves in step. The test for it used to be "no colon
    anywhere in the line", so a sentence carrying a time or a URL was shown
    neither here nor as a field -- it simply went missing.
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
        if line.strip() and metadata_pair(line) is None
    )
    return "\n".join(parts).strip()
