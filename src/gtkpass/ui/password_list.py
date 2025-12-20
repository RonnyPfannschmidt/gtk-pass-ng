"""Password list component for GTKPass.

This module provides the password list view that displays passwords grouped
by backend in a hierarchical tree structure.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402
from typing import Optional, Callable
import importlib.resources


@Gtk.Template(filename=str(
    importlib.resources.files("gtkpass.ui.blueprints") / "password_list.ui"
))
class PasswordTreeView(Gtk.ScrolledWindow):
    """Password tree view widget.

    Displays passwords organized by backend in a tree structure.
    Backends appear as root nodes with their own icons and loading indicators.
    """
    
    __gtype_name__ = "PasswordTreeView"
    
    # Template children
    tree_view: Gtk.TreeView = Gtk.Template.Child()
    icon_renderer: Gtk.CellRendererPixbuf = Gtk.Template.Child()
    spinner_renderer: Gtk.CellRendererSpinner = Gtk.Template.Child()
    text_renderer: Gtk.CellRendererText = Gtk.Template.Child()

    # Column indices in TreeStore
    COL_NAME = 0       # Display name (backend name or password name)
    COL_ICON = 1       # Icon name
    COL_BACKEND_ID = 2 # Backend ID (for root nodes) or None
    COL_PASSWORD = 3   # Password name (for password entries) or None
    COL_LOADING = 4    # True if loading, False otherwise

    def __init__(self, **kwargs):
        """Initialize the password tree view."""
        super().__init__(**kwargs)
        
        # Create tree store: name, icon, backend_id, password_name, loading
        self.store = Gtk.TreeStore(str, str, str, str, bool)
        self.tree_view.set_model(self.store)
        
        # Get the column from the tree view
        column = self.tree_view.get_column(0)
        
        # Configure renderers
        column.add_attribute(self.icon_renderer, "icon-name", self.COL_ICON)
        column.add_attribute(self.text_renderer, "text", self.COL_NAME)
        
        # Set spinner data func
        column.set_cell_data_func(
            self.spinner_renderer,
            self._spinner_data_func
        )
        
        # Configure selection
        selection = self.tree_view.get_selection()
        selection.set_mode(Gtk.SelectionMode.SINGLE)
        
        # Callbacks
        self._on_password_selected: Optional[Callable] = None
    
    def _spinner_data_func(self, column, cell, model, iter, data):
        """Update spinner visibility and state based on loading flag."""
        loading = model.get_value(iter, self.COL_LOADING)
        cell.set_property("visible", loading)
        cell.set_property("active", loading)
    
    def add_backend(self, backend_id: str, backend_name: str, icon_name: str) -> Gtk.TreeIter:
        """Add a backend as a root node.
        
        Args:
            backend_id: Backend identifier
            backend_name: Display name
            icon_name: Icon name
        
        Returns:
            TreeIter for the backend node
        """
        return self.store.append(None, [
            backend_name,
            icon_name,
            backend_id,
            None,
            False,  # Not loading initially
        ])
    
    def set_backend_loading(self, backend_iter: Gtk.TreeIter, loading: bool):
        """Set loading state for a backend.
        
        Args:
            backend_iter: Backend tree iter
            loading: True to show spinner, False to hide
        """
        self.store.set_value(backend_iter, self.COL_LOADING, loading)
        self.store.set_value(backend_iter, self.COL_ICON, "" if loading else None)
    
    def add_password(self, backend_iter: Gtk.TreeIter, name: str, full_path: str):
        """Add a password entry under a backend.
        
        Args:
            backend_iter: Parent backend tree iter
            name: Password display name (just the final component)
            full_path: Full password path
        """
        # For hierarchical paths like "work/email", create nested structure
        parts = full_path.split("/")
        current_parent = backend_iter
        current_path = []
        
        for i, part in enumerate(parts):
            current_path.append(part)
            path_str = "/".join(current_path)
            
            # Check if this node already exists
            existing = self._find_child(current_parent, part)
            
            if existing:
                current_parent = existing
            else:
                # Create new node
                is_leaf = (i == len(parts) - 1)
                icon = "" if is_leaf else "folder-symbolic"
                password_name = path_str if is_leaf else None
                
                new_iter = self.store.append(current_parent, [
                    part,
                    icon,
                    None,  # Not a backend
                    password_name,
                    False,  # Not loading
                ])
                current_parent = new_iter
    
    def _find_child(self, parent_iter: Gtk.TreeIter, name: str) -> Optional[Gtk.TreeIter]:
        """Find a child node by name.
        
        Args:
            parent_iter: Parent iterator
            name: Child name to find
        
        Returns:
            TreeIter if found, None otherwise
        """
        child_iter = self.store.iter_children(parent_iter)
        while child_iter:
            child_name = self.store.get_value(child_iter, self.COL_NAME)
            if child_name == name:
                return child_iter
            child_iter = self.store.iter_next(child_iter)
        return None
    
    def clear_backend_passwords(self, backend_iter: Gtk.TreeIter):
        """Remove all password entries under a backend.
        
        Args:
            backend_iter: Backend tree iter
        """
        # Remove all children
        while True:
            child = self.store.iter_children(backend_iter)
            if not child:
                break
            self.store.remove(child)
    
    def clear_all(self):
        """Clear all backends and passwords."""
        self.store.clear()
    
    def get_selected_password(self) -> Optional[tuple[str, str]]:
        """Get the currently selected password.
        
        Returns:
            Tuple of (backend_id, password_name) or None if no password selected
        """
        selection = self.tree_view.get_selection()
        model, iter = selection.get_selected()
        
        if not iter:
            return None
        
        # Check if this is a password (leaf node)
        password_name = model.get_value(iter, self.COL_PASSWORD)
        if not password_name:
            return None  # It's a backend or folder, not a password
        
        # Find parent backend
        backend_id = None
        current = iter
        while current:
            bid = model.get_value(current, self.COL_BACKEND_ID)
            if bid:
                backend_id = bid
                break
            current = model.iter_parent(current)
        
        if backend_id:
            return (backend_id, password_name)
        return None
    
    def connect_password_selected(self, callback: Callable[[str, str], None]):
        """Connect callback for password selection.
        
        Args:
            callback: Function called with (backend_id, password_name)
        """
        self._on_password_selected = callback
        
        def on_selection_changed(selection):
            result = self.get_selected_password()
            if result and self._on_password_selected:
                backend_id, password_name = result
                self._on_password_selected(backend_id, password_name)
        
        selection = self.tree_view.get_selection()
        selection.connect("changed", on_selection_changed)
    
    def expand_first_level(self):
        """Expand all backend nodes (first level)."""
        iter = self.store.get_iter_first()
        while iter:
            path = self.store.get_path(iter)
            self.tree_view.expand_row(path, False)
            iter = self.store.iter_next(iter)
    
    def expand_all(self):
        """Expand all nodes recursively."""
        self.tree_view.expand_all()


# Backwards compatibility aliases
PasswordList = PasswordTreeView

