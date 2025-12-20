"""Password detail view component for GTKPass.

This module provides the detail view that displays full password information
when a password is selected from the list.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402
from typing import Optional
import importlib.resources


@Gtk.Template(filename=str(
    importlib.resources.files("gtkpass.ui.blueprints") / "password_detail.ui"
))
class PasswordDetailView(Gtk.Box):
    """Password detail view widget.

    Displays detailed information about a selected password including:
    - Password name
    - Username
    - Password (with show/hide)
    - URL
    - Notes
    - Copy buttons for each field
    
    Supports async loading with spinner and clears password from memory
    when view loses focus or selection changes.
    """
    
    __gtype_name__ = "PasswordDetailView"
    
    # Template children
    stack: Gtk.Stack = Gtk.Template.Child()
    spinner_box: Gtk.Box = Gtk.Template.Child()
    spinner: Gtk.Spinner = Gtk.Template.Child()
    spinner_label: Gtk.Label = Gtk.Template.Child()
    prefs_page: Adw.PreferencesPage = Gtk.Template.Child()
    info_group: Adw.PreferencesGroup = Gtk.Template.Child()
    name_row: Adw.ActionRow = Gtk.Template.Child()
    username_row: Adw.ActionRow = Gtk.Template.Child()
    password_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    url_row: Adw.ActionRow = Gtk.Template.Child()
    notes_group: Adw.PreferencesGroup = Gtk.Template.Child()
    notes_label: Gtk.Label = Gtk.Template.Child()

    def __init__(self, **kwargs):
        """Initialize the password detail view."""
        super().__init__(**kwargs)
        
        # Set initial stack state
        self.stack.set_visible_child_name("content")
        
        # Track current password entry for clearing
        self._current_entry: Optional[object] = None  # PasswordEntry object

    def show_loading(self):
        """Show loading spinner."""
        self.stack.set_visible_child_name("loading")
        self.spinner.set_spinning(True)

    def hide_loading(self):
        """Hide loading spinner and show content."""
        self.spinner.set_spinning(False)
        self.stack.set_visible_child_name("content")

    def set_password_data(
        self,
        name: str,
        username: str = "",
        password: str = "",
        url: str = "",
        notes: str = "",
    ):
        """Set the password data to display.

        Args:
            name: Password name
            username: Username associated with password
            password: The actual password
            url: URL/website
            notes: Additional notes
        """
        self.name_row.set_subtitle(name)
        self.username_row.set_subtitle(username or "—")
        self.password_row.set_text(password)
        self.url_row.set_subtitle(url or "—")
        self.notes_label.set_text(notes or "No notes")
        
        self.hide_loading()

    def set_password_entry(self, entry: Optional[object]):
        """Set the current password entry (for later clearing).
        
        Args:
            entry: PasswordEntry object or None
        """
        # Clear previous entry if exists
        if self._current_entry and hasattr(self._current_entry, 'clear_password'):
            self._current_entry.clear_password()
        
        self._current_entry = entry

    def clear(self):
        """Clear all displayed password data and clear from memory."""
        # Clear from memory first
        if self._current_entry and hasattr(self._current_entry, 'clear_password'):
            self._current_entry.clear_password()
        self._current_entry = None
        
        # Clear UI
        self.set_password_data("", "", "", "", "")
        
    def on_focus_lost(self):
        """Called when view loses focus - clears password from memory."""
        if self._current_entry and hasattr(self._current_entry, 'clear_password'):
            self._current_entry.clear_password()

