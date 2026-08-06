"""Dialog for editing one password entry.

An entry is free text: the password on the first line, and whatever the store
happens to keep after it. The dialog splits on exactly that boundary and joins
it back, because what it hands over replaces the entry wholesale -- anything it
dropped on the way would be lost.

Nothing here logs its contents. The widgets hold plaintext while the dialog is
open, which is unavoidable for an editor, but it must not leak any further.
"""

import importlib.resources
from typing import ClassVar

from gtkpass._gi import Adw, GObject, Gtk
from gtkpass.backends import PasswordEntry


@Gtk.Template(
    filename=str(
        importlib.resources.files("gtkpass.ui.blueprints") / "password_edit.ui"
    )
)
class PasswordEditDialog(Adw.Dialog):
    """Edits an entry and emits the replacement content.

    The dialog does not write anything itself: it emits ``saved`` and lets the
    window decide which backend to put it through and how to report failure.
    """

    __gtype_name__ = "PasswordEditDialog"

    __gsignals__: ClassVar[dict] = {
        # (full replacement content)
        "saved": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    name_row: Adw.ActionRow = Gtk.Template.Child()
    password_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    details_view: Gtk.TextView = Gtk.Template.Child()
    cancel_button: Gtk.Button = Gtk.Template.Child()
    save_button: Gtk.Button = Gtk.Template.Child()

    def load(self, entry: PasswordEntry) -> None:
        """Fill the dialog in from a decrypted entry."""
        self.name_row.set_subtitle(entry.name)

        password, _, details = (entry.content or "").partition("\n")
        self.password_row.set_text(password)
        self.details_view.get_buffer().set_text(details)

    @property
    def content(self) -> str:
        """The edited entry, ready to hand to a backend.

        Always newline-terminated after the password, which is how stores write
        an entry even when it has nothing below it.
        """
        buffer = self.details_view.get_buffer()
        details = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        return f"{self.password_row.get_text()}\n{details}"

    @Gtk.Template.Callback()
    def _on_save(self, _button) -> None:
        # An empty first line would leave the entry with no password at all,
        # and every backend would happily store that.
        if not self.password_row.get_text():
            self.password_row.grab_focus()
            return
        self.emit("saved", self.content)
        self.close()

    @Gtk.Template.Callback()
    def _on_cancel(self, _button) -> None:
        self.close()
