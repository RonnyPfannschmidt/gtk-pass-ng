"""The rotation wizard: replacing a password without losing the account.

Rotating is what people reach for most often after reading an entry, and doing
it through the editor gets the order wrong. The editor writes the store first
and the site second, so a site that refuses the new password -- too long, no
symbols, a change form that fails halfway -- leaves the store holding a
password that does not work, and the account reachable only through a reset.

So this puts the store last. Make the replacement, put it into the site, say
whether that worked, and only then write. Until the last page is confirmed the
store still holds the password that works, and this keeps that one on screen
where it can be copied: a change form asks for the current password first.

Nothing here writes anything and nothing here touches the clipboard. It emits
``rotated`` and ``copy-requested``, and the window -- which owns the backends
and the one clipboard that gets cleared on a timer -- does both.
"""

import importlib.resources
from typing import ClassVar

from gtkpass._gi import Adw, GObject, Gtk
from gtkpass.backends import PasswordEntry
from gtkpass.ui.password_detail import field_of, is_openable, launch_uri
from gtkpass.ui.password_generator import PasswordGeneratorGroup


@Gtk.Template(
    filename=str(
        importlib.resources.files("gtkpass.ui.blueprints") / "password_rotate.ui"
    )
)
class PasswordRotateDialog(Adw.Dialog):
    """Walks a password change through in the order that cannot lose an account."""

    __gtype_name__ = "PasswordRotateDialog"

    __gsignals__: ClassVar[dict] = {
        # (full replacement content)
        "rotated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # (field label, value) -- the same signal the detail pane emits, so the
        # window handles both with one handler and one clipboard.
        "copy-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    navigation: Adw.NavigationView = Gtk.Template.Child()

    entry_row: Adw.ActionRow = Gtk.Template.Child()
    current_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    copy_current_button: Gtk.Button = Gtk.Template.Child()
    new_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    copy_new_button: Gtk.Button = Gtk.Template.Child()
    generator: PasswordGeneratorGroup = Gtk.Template.Child()
    cancel_button: Gtk.Button = Gtk.Template.Child()
    to_site_button: Gtk.Button = Gtk.Template.Child()

    url_row: Adw.ActionRow = Gtk.Template.Child()
    open_url_button: Gtk.Button = Gtk.Template.Child()
    username_row: Adw.ActionRow = Gtk.Template.Child()
    copy_username_button: Gtk.Button = Gtk.Template.Child()
    site_new_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    site_current_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    to_confirm_button: Gtk.Button = Gtk.Template.Child()

    save_button: Gtk.Button = Gtk.Template.Child()
    rotate_note: Gtk.Label = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        #: Everything below the password, kept verbatim. The reason to rotate
        #: rather than delete and add again is that this survives.
        self._details = ""
        #: What the store holds now, so that it can be copied and so that
        #: rotating to the same value can be recognised as no rotation at all.
        self._current = ""
        #: The site, when the entry names one that is safe to launch.
        self._openable_url = ""

    def load(self, entry: PasswordEntry, store_name: str) -> bool:
        """Fill the wizard in from a decrypted entry.

        Args:
            entry: The entry to rotate, with its content loaded.
            store_name: The backend's display name, for the note at the end.

        Returns:
            Whether there is anything to rotate. False for an entry whose
            content never arrived -- the pane can hand one over while a decrypt
            is still in flight, and writing that would replace the entry with a
            password and nothing else.
        """
        if not entry.content:
            return False

        self._current, _, self._details = entry.content.partition("\n")

        self.entry_row.set_title(entry.name)
        self.entry_row.set_subtitle(f"in {store_name}")
        self.current_row.set_text(self._current)
        self.site_current_row.set_text(self._current)

        username = field_of(entry, "Username")
        self.username_row.set_subtitle(username)
        self.username_row.set_visible(bool(username))

        url = field_of(entry, "URL")
        self.url_row.set_subtitle(url)
        self.url_row.set_visible(bool(url))
        # The same rule the detail pane applies: a web address and nothing
        # else, because a synced store carries whatever another machine wrote.
        self._openable_url = url if is_openable(url) else ""
        self.open_url_button.set_visible(bool(self._openable_url))

        self.rotate_note.set_label(
            f"Everything else in {entry.name} is kept exactly as it is."
        )

        # Generated straight away: nobody opens this wizard not wanting a new
        # password, and making them click Generate first is a step that has
        # only one answer.
        self._take(self.generator.generate())
        return True

    @property
    def content(self) -> str:
        """The rotated entry, ready to hand to a backend.

        The new password on the first line and everything else exactly as it
        was, which is the whole reason this is a rotation and not a delete
        followed by an add.
        """
        return f"{self.new_row.get_text()}\n{self._details}"

    # -- making the replacement ----------------------------------------------

    def _take(self, password: str) -> None:
        """Show a new password on both pages that display it.

        Revealed, as the add and edit dialogs reveal one: somebody who has just
        generated a password has not seen it yet, and a row of dots gives them
        no reason to believe anything happened.
        """
        self.new_row.set_text(password)
        self.site_new_row.set_text(password)
        for row in (self.new_row, self.site_new_row):
            delegate = row.get_delegate()
            if delegate is not None:
                delegate.set_visibility(True)

    @Gtk.Template.Callback()
    def _on_generated(self, _group, password: str) -> None:
        self._take(password)

    # -- moving through it ---------------------------------------------------

    @Gtk.Template.Callback()
    def _on_to_site(self, _button) -> None:
        """Go on to the site, once there is something to take to it."""
        password = self.new_row.get_text()
        if not password:
            self.new_row.grab_focus()
            return
        if password == self._current:
            # Not a rotation. Nothing would change anywhere, and the pages
            # after this would walk somebody through doing nothing.
            self.new_row.grab_focus()
            return

        # Typed rather than generated: the second page shows it too.
        self.site_new_row.set_text(password)
        self.navigation.push_by_tag("site")

    @Gtk.Template.Callback()
    def _on_to_confirm(self, _button) -> None:
        self.navigation.push_by_tag("confirm")

    @Gtk.Template.Callback()
    def _on_save(self, _button) -> None:
        self.emit("rotated", self.content)
        self.close()

    @Gtk.Template.Callback()
    def _on_cancel(self, _button) -> None:
        self.close()

    # -- copying and opening -------------------------------------------------

    @Gtk.Template.Callback()
    def _on_copy_current(self, _button) -> None:
        self.emit("copy-requested", "Password", self._current)

    @Gtk.Template.Callback()
    def _on_copy_new(self, _button) -> None:
        self.emit("copy-requested", "Password", self.new_row.get_text())

    @Gtk.Template.Callback()
    def _on_copy_username(self, _button) -> None:
        self.emit("copy-requested", "Username", self.username_row.get_subtitle() or "")

    @Gtk.Template.Callback()
    def _on_open_url(self, _button) -> None:
        if self._openable_url:
            launch_uri(self._openable_url)
