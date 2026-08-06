"""Password list component for GTKPass.

Displays passwords grouped by backend in a hierarchical tree: backends are the
root rows, path components below them become folders, and the leaves are the
entries themselves.

The tree is a ``Gtk.ColumnView`` over a ``Gtk.TreeListModel`` of
:class:`PasswordNode` objects. The nodes are the model the window populates and
that selection reads back; the view only renders them.
"""

import importlib.resources
from collections.abc import Callable

from gtkpass._gi import Gio, GObject, Gtk


class PasswordNode(GObject.Object):
    """One row in the sidebar: a backend, a folder, or an entry.

    The row template in ``password_list.blp`` binds to these properties by
    name, so the GType name here has to stay in step with the
    ``$GTKPassPasswordNode`` casts over there.
    """

    __gtype_name__ = "GTKPassPasswordNode"

    name = GObject.Property(type=str, default="")
    icon_name = GObject.Property(type=str, default="")

    def __init__(
        self,
        name: str,
        icon_name: str = "",
        backend_id: str = "",
        password_name: str = "",
    ) -> None:
        super().__init__(name=name, icon_name=icon_name)
        #: The backend this row belongs to. Every descendant carries it, so a
        #: selected entry knows its backend without walking back up the tree.
        self.backend_id = backend_id
        #: Full path of the entry; empty on backend and folder rows, which is
        #: what makes a row selectable as a password or not.
        self.password_name = password_name
        self.children: Gio.ListStore = Gio.ListStore(item_type=PasswordNode)


def _children_of(node: PasswordNode) -> Gio.ListStore | None:
    """Child model for a row, or None for one that cannot have children.

    Decided by what the row *is* rather than by whether it happens to be empty
    yet: the tree model caches this answer the first time it renders a row, and
    the window fills a backend in only after adding it.
    """
    return None if node.password_name else node.children


@Gtk.Template(
    filename=str(
        importlib.resources.files("gtkpass.ui.blueprints") / "password_list.ui"
    )
)
class PasswordTreeView(Gtk.ScrolledWindow):
    """Password tree view widget.

    Displays passwords organized by backend in a tree structure, with backends
    as root nodes carrying their own icons.
    """

    __gtype_name__ = "PasswordTreeView"

    column_view: Gtk.ColumnView = Gtk.Template.Child()

    def __init__(self, **kwargs):
        """Initialize the password tree view."""
        super().__init__(**kwargs)

        #: Backend rows. Everything else hangs below one of them.
        self.root: Gio.ListStore = Gio.ListStore(item_type=PasswordNode)
        self.tree_model = Gtk.TreeListModel.new(
            self.root,
            passthrough=False,
            autoexpand=False,
            create_func=_children_of,
        )
        # Nothing is selected until the user picks something: autoselect would
        # fire the selection handler for whichever row happened to load first,
        # decrypting an entry nobody asked for.
        self.selection = Gtk.SingleSelection(
            model=self.tree_model, autoselect=False, can_unselect=True
        )
        self.column_view.set_model(self.selection)

        self._on_password_selected: Callable[[str, str], None] | None = None
        self.selection.connect("notify::selected-item", self._selection_changed)

    def _selection_changed(self, *_args) -> None:
        selected = self.get_selected_password()
        if selected and self._on_password_selected:
            self._on_password_selected(*selected)

    def add_backend(
        self, backend_id: str, backend_name: str, icon_name: str
    ) -> PasswordNode:
        """Add a backend as a root node.

        Args:
            backend_id: Backend identifier
            backend_name: Display name
            icon_name: Icon name

        Returns:
            The node, to be passed back as the parent of its entries.
        """
        node = PasswordNode(
            name=backend_name, icon_name=icon_name, backend_id=backend_id
        )
        self.root.append(node)
        return node

    def add_password(self, backend: PasswordNode, path: str) -> PasswordNode:
        """Add an entry under a backend, creating folder rows as needed.

        Args:
            backend: Node returned by :meth:`add_backend`
            path: Full entry path, ``work/mail`` style

        Returns:
            The leaf node for the entry.
        """
        parent = backend
        parts = path.split("/")

        for depth, part in enumerate(parts):
            existing = self._child_named(parent, part)
            if existing is not None:
                parent = existing
                continue

            is_leaf = depth == len(parts) - 1
            node = PasswordNode(
                name=part,
                icon_name="" if is_leaf else "folder-symbolic",
                backend_id=backend.backend_id,
                password_name="/".join(parts[: depth + 1]) if is_leaf else "",
            )
            parent.children.append(node)
            parent = node

        return parent

    @staticmethod
    def _child_named(parent: PasswordNode, name: str) -> PasswordNode | None:
        """Find a child row by name, so a shared folder is created once."""
        for index in range(parent.children.get_n_items()):
            child = parent.children.get_item(index)
            if child.name == name:
                return child
        return None

    def clear_backend_passwords(self, backend: PasswordNode) -> None:
        """Remove all entries under a backend."""
        backend.children.remove_all()

    def clear_all(self) -> None:
        """Clear all backends and passwords."""
        self.root.remove_all()

    def get_selected_password(self) -> tuple[str, str] | None:
        """Get the currently selected password.

        Returns:
            Tuple of (backend_id, password_name), or None when the selection is
            a backend, a folder, or nothing at all.
        """
        row = self.selection.get_selected_item()
        if row is None:
            return None

        node = row.get_item()
        if not node.password_name:
            return None
        return (node.backend_id, node.password_name)

    def connect_password_selected(self, callback: Callable[[str, str], None]) -> None:
        """Connect callback for password selection.

        Args:
            callback: Function called with (backend_id, password_name)
        """
        self._on_password_selected = callback

    def expand_first_level(self) -> None:
        """Expand all backend nodes, leaving their folders closed."""
        self._expand(lambda row: row.get_depth() == 0)

    def expand_all(self) -> None:
        """Expand all nodes recursively."""
        self._expand(lambda row: True)

    def _expand(self, wanted: Callable[[Gtk.TreeListRow], bool]) -> None:
        """Expand matching rows, including any they reveal on the way.

        The model grows as rows open, so the bound is re-read every step rather
        than taken once up front.
        """
        index = 0
        while index < self.tree_model.get_n_items():
            row = self.tree_model.get_row(index)
            if row is not None and wanted(row):
                row.set_expanded(True)
            index += 1
