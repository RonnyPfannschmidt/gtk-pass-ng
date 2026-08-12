"""Dialog for adding one password entry.

The `+` button opened a "Not Implemented Yet" dialog for as long as there has
been a `+` button, while every backend that can write has implemented
``add_password`` all along. This is what was missing.

As with the editor, nothing here writes anything: the dialog emits ``added``
and the window decides which backend to put it through and how to report a
failure.
"""

import importlib.resources
from typing import ClassVar

from gtkpass._gi import Adw, GObject, Gtk
from gtkpass.utils.generate import generate_password


@Gtk.Template(
    filename=str(importlib.resources.files("gtkpass.ui.blueprints") / "password_add.ui")
)
class PasswordAddDialog(Adw.Dialog):
    """Collects a store, a name and an entry, and emits the result."""

    __gtype_name__ = "PasswordAddDialog"

    __gsignals__: ClassVar[dict] = {
        # (backend id, entry name, full content)
        "added": (GObject.SignalFlags.RUN_FIRST, None, (str, str, str)),
    }

    backend_row: Adw.ComboRow = Gtk.Template.Child()
    name_row: Adw.EntryRow = Gtk.Template.Child()
    password_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    generate_button: Gtk.Button = Gtk.Template.Child()
    length_row: Adw.SpinRow = Gtk.Template.Child()
    symbols_row: Adw.SwitchRow = Gtk.Template.Child()
    details_view: Gtk.TextView = Gtk.Template.Child()
    cancel_button: Gtk.Button = Gtk.Template.Child()
    save_button: Gtk.Button = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        #: Backend ids in the order the combo row offers them.
        self._backend_ids: list[str] = []
        #: Entry names already in each store, so a collision is caught before
        #: the write rather than reported as a FileExistsError afterwards.
        self._taken: dict[str, set[str]] = {}

    def offer(
        self,
        backends: list[tuple[str, str]],
        taken: dict[str, set[str]] | None = None,
        preselect: str = "",
        folder: str = "",
    ) -> None:
        """Say which stores can be written to, and where the user was.

        Args:
            backends: (id, display name) pairs, writable ones only.
            taken: Entry names each store already holds, by backend id.
            preselect: Backend to start on -- whatever the sidebar was showing.
            folder: Folder to prefill the name with, so adding an entry while
                standing in ``work/`` starts there rather than at the root.
        """
        self._backend_ids = [backend_id for backend_id, _ in backends]
        self._taken = taken or {}

        names = Gtk.StringList()
        for _, display_name in backends:
            names.append(display_name)
        self.backend_row.set_model(names)
        # A choice of one is not a choice, and asking for it would make the
        # common case longer for nothing.
        self.backend_row.set_visible(len(backends) > 1)

        if preselect in self._backend_ids:
            self.backend_row.set_selected(self._backend_ids.index(preselect))

        if folder:
            self.name_row.set_text(f"{folder.rstrip('/')}/")
        # After the folder, so the caret lands at the end of it.
        self.name_row.grab_focus()
        self.name_row.select_region(-1, -1)

    @property
    def backend_id(self) -> str:
        """The store the entry is to go into."""
        selected = self.backend_row.get_selected()
        if 0 <= selected < len(self._backend_ids):
            return self._backend_ids[selected]
        return self._backend_ids[0] if self._backend_ids else ""

    @property
    def name(self) -> str:
        """The entry path, with the slashes tidied but not otherwise altered."""
        return "/".join(part for part in self.name_row.get_text().split("/") if part)

    @property
    def content(self) -> str:
        """The new entry, ready to hand to a backend."""
        buffer = self.details_view.get_buffer()
        details = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        return f"{self.password_row.get_text()}\n{details}"

    @Gtk.Template.Callback()
    def _on_generate(self, _button) -> None:
        """Fill the password in, and show it.

        Revealed on purpose: somebody who has just generated a password has not
        seen it yet, and a row of dots gives them no reason to believe anything
        happened.
        """
        self.password_row.set_text(
            generate_password(
                length=int(self.length_row.get_value()),
                symbols=self.symbols_row.get_active(),
            )
        )
        delegate = self.password_row.get_delegate()
        if delegate is not None:
            delegate.set_visibility(True)

    @Gtk.Template.Callback()
    def _on_name_changed(self, *_args) -> None:
        """Say that a name is already taken while it is still being typed."""
        self._validate_name()

    #: The name row doubles as where a clash is reported. There is no subtitle
    #: on an Adw.EntryRow to put it in, and a label that appears and disappears
    #: would shift every row below it as the user types.
    NAME_TITLE = "Name"
    NAME_TAKEN = "Name (an entry of this name is already there)"

    def _validate_name(self) -> bool:
        taken = bool(self.name) and self.name in self._taken.get(self.backend_id, set())
        if taken:
            self.name_row.add_css_class("error")
            self.name_row.set_title(self.NAME_TAKEN)
        else:
            self.name_row.remove_css_class("error")
            self.name_row.set_title(self.NAME_TITLE)
        return not taken

    @Gtk.Template.Callback()
    def _on_save(self, _button) -> None:
        """Refuse what a backend would refuse, before it costs a round trip."""
        if not self.name:
            self.name_row.grab_focus()
            return
        if not self._validate_name():
            self.name_row.grab_focus()
            return
        # An empty first line would leave the entry with no password at all,
        # and every backend would happily store that.
        if not self.password_row.get_text():
            self.password_row.grab_focus()
            return

        self.emit("added", self.backend_id, self.name, self.content)
        self.close()

    @Gtk.Template.Callback()
    def _on_cancel(self, _button) -> None:
        self.close()
