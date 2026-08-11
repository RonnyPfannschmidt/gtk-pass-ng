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

#: A leaf carries the same icon the application uses for itself, so an entry is
#: recognisable as one without counting indentation levels.
ENTRY_ICON = "dialog-password-symbolic"
FOLDER_ICON = "folder-symbolic"


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


class BackendEntries:
    """Everything one backend contributed, whether or not it is on screen.

    The sidebar is filtered by rebuilding it from these rather than by laying a
    ``Gtk.FilterListModel`` over the tree: a ``Gtk.TreeListModel`` materialises
    a folder's children only once that folder has been expanded, so a filter
    over the view would have matched whatever happened to be open at the time
    and missed the rest of the store entirely.
    """

    def __init__(self, backend_id: str, name: str, icon_name: str) -> None:
        self.backend_id = backend_id
        self.name = name
        self.icon_name = icon_name
        #: Full entry paths, in the order they were listed.
        self.entries: list[str] = []
        #: This backend's row while it is shown, None while it is filtered out.
        self.node: PasswordNode | None = None


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
        self._hide_column_header()

        self._on_password_selected: Callable[[str, str], None] | None = None
        self.selection.connect("notify::selected-item", self._selection_changed)

        #: What each backend contributed, kept so a filter can be lifted again.
        self._backends: list[BackendEntries] = []
        #: The search text the tree is currently narrowed to; empty means all.
        self._filter = ""

    def _hide_column_header(self) -> None:
        """Drop the header row of the one column the sidebar has.

        A single column with nothing to sort by has no title worth 30 pixels of
        a 250 pixel sidebar. ColumnView exposes no property for this, so the
        header row -- its first child -- is hidden directly; a test presents the
        widget and checks it stayed hidden, which is what would catch GTK
        rearranging its children under us.
        """
        header = self.column_view.get_first_child()
        if header is not None:
            header.set_visible(False)

    def _selection_changed(self, *_args) -> None:
        selected = self.get_selected_password()
        if selected and self._on_password_selected:
            self._on_password_selected(*selected)

    def add_backend(
        self, backend_id: str, backend_name: str, icon_name: str
    ) -> BackendEntries:
        """Add a backend as a root node.

        Args:
            backend_id: Backend identifier
            backend_name: Display name
            icon_name: Icon name

        Returns:
            The backend's record, to be passed back as the parent of its
            entries. It outlives the row, which a filter may take away and
            give back.
        """
        record = BackendEntries(backend_id, backend_name, icon_name)
        self._backends.append(record)
        if not self._filter:
            # Unfiltered, a backend has a row before it has entries: the window
            # adds every backend first and fills them in as the listings come
            # back, so an empty store still says it is there.
            self._node_for(record)
        return record

    def _node_for(self, record: BackendEntries) -> PasswordNode:
        """The backend's row, created if a filter had taken it away.

        Inserted where the record sits among the backends that are on screen,
        so the sidebar keeps the order the backends were added in however they
        come and go.
        """
        if record.node is not None:
            return record.node

        record.node = PasswordNode(
            name=record.name, icon_name=record.icon_name, backend_id=record.backend_id
        )
        position = sum(
            1
            for other in self._backends[: self._backends.index(record)]
            if other.node is not None
        )
        self.root.insert(position, record.node)
        return record.node

    def set_filter(self, text: str) -> int:
        """Narrow the tree to the entries whose path contains ``text``.

        Matching is a case-insensitive substring of the whole path, so ``work/``
        finds a folder and ``mail`` finds every entry called that wherever it
        sits. Folders that lead to a match are kept, and everything is expanded:
        a match inside a collapsed folder is a match nobody can see.

        Returns:
            How many entries matched, which is what tells an empty store apart
            from a search that found nothing.
        """
        self._filter = text.strip()

        self.root.remove_all()
        for record in self._backends:
            record.node = None

        matched = 0
        for record in self._backends:
            entries = [path for path in record.entries if self._matches(path)]
            matched += len(entries)
            if not self._filter:
                self._node_for(record)
            for path in entries:
                self._insert(record, path)

        if self._filter:
            self.expand_all()
        else:
            self.expand_first_level()
        return matched

    def _matches(self, path: str) -> bool:
        return self._filter.lower() in path.lower()

    def add_password(self, backend: BackendEntries, path: str) -> PasswordNode | None:
        """Add an entry under a backend, creating folder rows as needed.

        Args:
            backend: Record returned by :meth:`add_backend`
            path: Full entry path, ``work/mail`` style

        Returns:
            The leaf node for the entry, or None when a filter is on and the
            entry does not match it. The entry is remembered either way, so
            clearing the filter brings it back.
        """
        backend.entries.append(path)
        if not self._matches(path):
            return None
        node = self._insert(backend, path)
        if self._filter:
            # It arrived while a search was running -- a listing coming back
            # late, or an entry just saved -- so open the way down to it.
            self.expand_all()
        return node

    def _insert(self, backend: BackendEntries, path: str) -> PasswordNode:
        """Put one entry into the visible tree, building its folders."""
        parent = self._node_for(backend)
        parts = path.split("/")

        for depth, part in enumerate(parts):
            existing = self._child_named(parent, part)
            if existing is not None:
                parent = existing
                continue

            is_leaf = depth == len(parts) - 1
            node = PasswordNode(
                name=part,
                icon_name=ENTRY_ICON if is_leaf else FOLDER_ICON,
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

    def clear_backend_passwords(self, backend: BackendEntries) -> None:
        """Remove all entries under a backend."""
        backend.entries.clear()
        if backend.node is not None:
            backend.node.children.remove_all()

    def clear_all(self) -> None:
        """Clear all backends and passwords, filtered out ones included."""
        self._backends.clear()
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

    def selected_backend(self) -> str:
        """The backend the selected row belongs to, whatever kind of row it is.

        Every row carries its backend, so this answers for a folder and for a
        backend heading as well as for an entry -- which is what makes "add a
        password" land in the store the user is standing in.
        """
        row = self.selection.get_selected_item()
        return row.get_item().backend_id if row is not None else ""

    def selected_folder(self) -> str:
        """The folder the selection is standing in, without a trailing slash.

        A selected folder is that folder; a selected entry is the folder that
        holds it; a backend heading is the root of its store.
        """
        row = self.selection.get_selected_item()
        if row is None:
            return ""
        node = row.get_item()
        if node.password_name:
            folder, _, _ = node.password_name.rpartition("/")
            return folder
        return self._path_of(node)

    def _path_of(self, wanted: PasswordNode) -> str:
        """Where a folder row sits, by finding it again from the top.

        A node does not know its parent -- the tree is built downwards and the
        row template binds to the node, not to a path -- so this walks for it.
        Cheap enough: it runs once, when a dialog is opened.
        """

        def walk(store: Gio.ListStore, prefix: str) -> str | None:
            for index in range(store.get_n_items()):
                node = store.get_item(index)
                if node.password_name:
                    continue
                here = f"{prefix}/{node.name}" if prefix else node.name
                if node is wanted:
                    return here
                found = walk(node.children, here)
                if found is not None:
                    return found
            return None

        for record in self._backends:
            if record.node is wanted:
                # A backend heading: the root of its store, not a folder in it.
                return ""
            if record.node is not None:
                found = walk(record.node.children, "")
                if found is not None:
                    return found
        return ""

    def entry_names(self) -> dict[str, set[str]]:
        """Every entry each backend holds, filtered out ones included.

        What the add dialog checks a new name against, so a clash is caught
        while it is still being typed rather than reported as a FileExistsError
        once the store has been asked.
        """
        return {record.backend_id: set(record.entries) for record in self._backends}

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
