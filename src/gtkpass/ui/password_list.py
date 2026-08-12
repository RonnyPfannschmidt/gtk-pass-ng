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

from gtkpass._gi import Gdk, Gio, GObject, Graphene, Gtk

#: A leaf carries the same icon the application uses for itself, so an entry is
#: recognisable as one without counting indentation levels.
ENTRY_ICON = "dialog-password-symbolic"
FOLDER_ICON = "folder-symbolic"

#: Stands for "the listing does not mention this at all", which None cannot:
#: None is what a leaf maps to.
_ABSENT = object()


class PasswordNode(GObject.Object):
    """One row in the sidebar: a backend, a folder, or an entry.

    The row template in ``password_list.blp`` binds to these properties by
    name, so the GType name here has to stay in step with the
    ``$GTKPassPasswordNode`` casts over there.
    """

    __gtype_name__ = "GTKPassPasswordNode"

    name = GObject.Property(type=str, default="")
    icon_name = GObject.Property(type=str, default="")
    #: What the row says when the pointer rests on it. Empty for almost every
    #: row; a backend that would not load carries the reason it gave, which
    #: otherwise lived only in a toast that had five seconds and then went.
    tooltip = GObject.Property(type=str, default="")

    def __init__(
        self,
        name: str,
        icon_name: str = "",
        backend_id: str = "",
        password_name: str = "",
        tooltip: str = "",
        path: str = "",
    ) -> None:
        super().__init__(name=name, icon_name=icon_name, tooltip=tooltip)
        #: Where this row sits in its backend: ``work/mail`` for a folder of
        #: that name and for the entry inside it, empty for a backend heading.
        #: What a listing is reconciled against, and what says a row is still
        #: the same row.
        self.path = path
        #: The backend this row belongs to. Every descendant carries it, so a
        #: selected entry knows its backend without walking back up the tree.
        self.backend_id = backend_id
        #: Full path of the entry; empty on backend and folder rows, which is
        #: what makes a row selectable as a password or not.
        self.password_name = password_name
        self.children: Gio.ListStore = Gio.ListStore(item_type=PasswordNode)


class BackendEntries:
    """Everything one backend listed, whether or not it is on screen.

    The whole listing is kept, not just the visible part, because a search
    narrows the tree to what matches and clearing it has to bring the rest
    back. Searching is done this way rather than by laying a
    ``Gtk.FilterListModel`` over the tree because a ``Gtk.TreeListModel``
    materialises a folder's children only once that folder has been expanded,
    so a filter over the view would have matched whatever happened to be open
    and missed the rest of the store entirely.
    """

    def __init__(
        self, backend_id: str, name: str, icon_name: str, tooltip: str = ""
    ) -> None:
        self.backend_id = backend_id
        self.name = name
        self.icon_name = icon_name
        self.tooltip = tooltip
        #: Full entry paths, in the order they were listed.
        self.entries: list[str] = []
        #: This backend's row while it is shown, None while it is filtered out.
        self.node: PasswordNode | None = None


def _folder_tree(paths: list[str]) -> dict:
    """The paths as nested dictionaries: a name maps to its children, or None.

    ``None`` is a leaf. A name that is both -- an entry ``work`` beside entries
    under ``work/`` -- becomes the folder, because the folder is the thing that
    can hold the rest; the entry of that name is not reachable in the tree
    either way, and a store that contains both is already ambiguous.
    """
    tree: dict = {}
    for path in paths:
        parts = [part for part in path.split("/") if part]
        if not parts:
            continue
        here = tree
        for part in parts[:-1]:
            below = here.get(part)
            if not isinstance(below, dict):
                below = {}
                here[part] = below
            here = below
        here.setdefault(parts[-1], None)
    return tree


def _holds_a_folder(node: PasswordNode) -> bool:
    """Whether any of this row's children is a folder rather than an entry."""
    children = node.children
    return any(
        not children.get_item(index).password_name
        for index in range(children.get_n_items())
    )


def _descendants(widget: Gtk.Widget):
    """Every widget below ``widget``, depth first."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _descendants(child)
        child = child.get_next_sibling()


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
        self._install_context_menu()

        #: What each backend contributed, kept so a filter can be lifted again.
        self._backends: list[BackendEntries] = []
        #: The search text the tree is currently narrowed to; empty means all.
        self._filter = ""
        #: (backend id, path) of the rows that were open before a search
        #: rearranged the tree, so that clearing it puts them back. A listing
        #: needs none of this: it corrects the tree rather than replacing it,
        #: and the rows it leaves alone keep what the view knows about them.
        self._expanded: set[tuple[str, str]] = set()
        #: The entry that was selected then, which a search may have hidden.
        self._selected: tuple[str, str] | None = None
        #: Set while the selection is being put back, so that doing so does not
        #: read as the user choosing an entry.
        self._restoring = False

    def _install_context_menu(self) -> None:
        """Offer the entry actions where the entries are.

        The menu is declared in password_menu.blp and its items are window
        actions, so the tree neither builds it nor knows what the items do. It
        is parented to this widget by hand because a popover has no place in
        the tree's own layout: it is positioned over whichever row was clicked.
        """
        builder = Gtk.Builder.new_from_file(
            str(importlib.resources.files("gtkpass.ui.blueprints") / "password_menu.ui")
        )
        self._menu = builder.get_object("password_menu")
        self._menu.set_parent(self)

        # Right-click on a pointer, and press-and-hold on a touchscreen. The
        # metadata claims touch, and a context menu no finger can reach is one
        # of the places that claim comes apart.
        click = Gtk.GestureClick(button=3)
        click.connect("pressed", self._on_secondary_press)
        self.add_controller(click)

        press = Gtk.GestureLongPress(touch_only=True)
        press.connect("pressed", self._on_long_press)
        self.add_controller(press)

    def _on_secondary_press(self, gesture, _n_press, x, y) -> None:
        self._popup_at(x, y)

    def _on_long_press(self, gesture, x, y) -> None:
        self._popup_at(x, y)

    def _popup_at(self, x: float, y: float) -> None:
        """Select whatever is under the pointer, then offer the menu there.

        Selecting first is what makes the menu about the row it was opened
        over. Without it the actions would act on whatever had been selected
        beforehand, which is the row the user is looking away from.
        """
        row = self._row_at(y)
        if row is None:
            return
        self.selection.set_selected(row)

        # Built empty and filled in: passing the fields to the constructor is
        # deprecated for a boxed type, and silently ignored.
        at = Gdk.Rectangle()
        at.x, at.y, at.width, at.height = int(x), int(y), 1, 1
        self._menu.set_pointing_to(at)
        self._menu.popup()

    def _row_at(self, y: float) -> int | None:
        """Which row of the model sits at ``y``, in this widget's coordinates.

        A ColumnView offers no lookup from a position to a row, and its row
        widgets are recycled, so neither their order among the children nor
        their identity says which item they are showing. What is dependable is
        that every row here is the same height -- one template, one line, no
        wrapping -- so one measured row answers for all of them.

        Measured rather than divided out of the total: the view is stretched to
        fill its viewport, so its height is the scrolled window's whenever the
        list is shorter than that, and dividing by the number of rows would put
        every click on a row of its own.

        The point is translated into the ColumnView's own coordinates first,
        which is what accounts for the scroll position: the gesture reports
        where in the viewport the click was, and the list is taller than that.
        """
        rows = self.tree_model.get_n_items()
        if not rows:
            return None

        ok, point = self.compute_point(self.column_view, Graphene.Point().init(0, y))
        if not ok:
            return None

        header = self.column_view.get_first_child()
        top = header.get_height() if header is not None and header.get_visible() else 0
        row_height = self._row_height()
        if row_height <= 0:
            return None

        position = int((point.y - top) // row_height)
        return position if 0 <= position < rows else None

    def _row_height(self) -> int:
        """How tall one row is, taken from one that has been drawn.

        Zero before the view has had a layout pass, which is the answer that
        makes _row_at decline rather than guess.
        """
        for child in _descendants(self.column_view):
            if child.__gtype__.name == "GtkColumnViewRowWidget" and child.get_height():
                return child.get_height()
        return 0

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
        if self._restoring:
            # Putting the highlight back on the entry the pane is already
            # showing. Announcing it would decrypt that entry a second time.
            return
        selected = self.get_selected_password()
        if selected and self._on_password_selected:
            self._on_password_selected(*selected)

    def add_backend(
        self, backend_id: str, backend_name: str, icon_name: str, tooltip: str = ""
    ) -> BackendEntries:
        """Add a backend as a root node.

        Args:
            backend_id: Backend identifier
            backend_name: Display name
            icon_name: Icon name
            tooltip: What the row says when the pointer rests on it, which for
                a backend that would not load is why

        Returns:
            The backend's record, to be passed back as the parent of its
            entries. It outlives the row, which a filter may take away and
            give back.
        """
        record = BackendEntries(backend_id, backend_name, icon_name, tooltip)
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
            name=record.name,
            icon_name=record.icon_name,
            backend_id=record.backend_id,
            tooltip=record.tooltip,
        )
        position = sum(
            1
            for other in self._backends[: self._backends.index(record)]
            if other.node is not None
        )
        self.root.insert(position, record.node)
        return record.node

    # -- reconciling ---------------------------------------------------------
    #
    # A listing does not rebuild the tree, it corrects it. Expansion lives on a
    # GtkTreeListRow and a row belongs to an item, so a tree rebuilt out of new
    # PasswordNode objects is a tree of new rows with every folder shut -- and
    # no amount of noting the old state and replaying it puts back what the
    # view itself knew, because the scroll position goes with it and every row
    # is re-rendered for the sake of the one entry that changed.

    def sync_backends(
        self, backends: list[tuple[str, str, str, str]]
    ) -> list[BackendEntries]:
        """Bring the backend rows in line with ``(id, name, icon, tooltip)``.

        A backend that is still configured keeps its row, and with it every
        folder open below it. One that has gone is removed, one that is new is
        added, and one that was renamed has its row relabelled in place.

        Returns:
            The records, in the order given, to be filled in as their listings
            arrive.
        """
        wanted = [backend_id for backend_id, _, _, _ in backends]
        by_id = {record.backend_id: record for record in self._backends}

        for record in list(self._backends):
            if record.backend_id not in wanted:
                self._drop(record)

        records: list[BackendEntries] = []
        for backend_id, name, icon_name, tooltip in backends:
            existing = by_id.get(backend_id)
            if existing is None:
                record = BackendEntries(backend_id, name, icon_name, tooltip)
                self._backends.append(record)
            else:
                record = existing
                record.name, record.icon_name, record.tooltip = name, icon_name, tooltip
                if record.node is not None:
                    # Relabelled rather than replaced: the row template binds
                    # these, so the sidebar redraws and stays where it is.
                    record.node.name = name
                    record.node.icon_name = icon_name
                    record.node.tooltip = tooltip
            records.append(record)

        # Kept in the order asked for, so the sidebar reads as the settings do.
        self._backends.sort(key=lambda record: wanted.index(record.backend_id))
        if not self._filter:
            for record in self._backends:
                self._node_for(record)
        return records

    def _drop(self, record: BackendEntries) -> None:
        """Take one backend's row away, if it has one."""
        if record.node is not None:
            found, position = self.root.find(record.node)
            if found:
                self.root.remove(position)
        self._backends.remove(record)

    def sync_entries(self, record: BackendEntries, paths: list[str]) -> None:
        """Bring one backend's subtree in line with ``paths``.

        Everything it lists is remembered, so that clearing a search can bring
        back what the search hid; what is shown is what passes the filter.
        """
        record.entries = list(paths)
        visible = [path for path in paths if self._matches(path)]

        # Nothing to show from this backend. Under a search that means its row
        # goes; unfiltered it stays, because an empty store is still a store
        # and saying so is the whole point of its row.
        if not visible and self._filter:
            if record.node is not None:
                found, position = self.root.find(record.node)
                if found:
                    self.root.remove(position)
                record.node = None
            return

        node = self._node_for(record)
        self._reconcile(node, _folder_tree(visible), record.backend_id, "")

    def _reconcile(
        self, parent: PasswordNode, wanted: dict, backend_id: str, prefix: str
    ) -> None:
        """Make ``parent``'s children the ones ``wanted`` describes.

        Rows that are still right are left alone -- the same object in the same
        place, which is what the view needs to keep them open. Only what
        actually differs is inserted or removed, so a listing that says what is
        already there emits nothing at all.
        """
        store = parent.children

        index = 0
        while index < store.get_n_items():
            child = store.get_item(index)
            below = wanted.get(child.name, _ABSENT)
            # A leaf that became a folder, or the other way about, is not the
            # same row wearing a different hat: it is replaced.
            if below is _ABSENT or (below is None) != bool(child.password_name):
                store.remove(index)
                continue
            index += 1

        # Folders first, then entries, each alphabetical. A folder is a place
        # to go and an entry is a thing to open; interleaving them makes the
        # reader sort by icon on every glance. The order is also what lets a
        # reconciliation find the row it is looking for rather than inserting
        # a second one beside it, so it has to be a property of the tree
        # rather than of whoever happened to build it.
        for position, name in enumerate(
            sorted(wanted, key=lambda name: (wanted[name] is None, name))
        ):
            below = wanted[name]
            here = f"{prefix}/{name}" if prefix else name

            child = store.get_item(position)
            if child is None or child.name != name:
                found = self._find_after(store, name, position)
                if found is None:
                    child = PasswordNode(
                        name=name,
                        icon_name=ENTRY_ICON if below is None else FOLDER_ICON,
                        backend_id=backend_id,
                        password_name=here if below is None else "",
                        path=here,
                    )
                    store.insert(position, child)
                else:
                    # Out of order rather than missing. Moving it costs the row
                    # its expansion, which is why the tree is kept sorted: once
                    # it is, nothing is ever out of order again.
                    child = store.get_item(found)
                    store.remove(found)
                    store.insert(position, child)

            if below is not None:
                self._reconcile(child, below, backend_id, here)

    @staticmethod
    def _find_after(store: Gio.ListStore, name: str, start: int) -> int | None:
        for index in range(start, store.get_n_items()):
            if store.get_item(index).name == name:
                return index
        return None

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
        wanted = text.strip()
        # Whether this call is the end of a search, which is the one moment
        # the remembered shape is put back -- including when that shape was
        # "nothing was open", which is not the same as having nothing to say.
        leaving = bool(self._filter) and not wanted
        if not self._filter and wanted:
            # A search is about to expand everything it matched, and hide the
            # rest. Note how the tree was left, so clearing it can put it back.
            self._remember_shape()
        self._filter = wanted

        matched = 0
        for record in self._backends:
            matched += sum(1 for path in record.entries if self._matches(path))
            # Reconciled like a listing, so a row that survives the search
            # keeps whatever the view knew about it.
            self.sync_entries(record, record.entries)

        if self._filter:
            self.expand_all()
        elif leaving:
            # Back to the shape the user had before they searched, including
            # the entry they had picked -- a search that hid it took the
            # selection with it.
            self.restore_expansion()
            self.restore_selection()
        else:
            self.expand_first_level()
        return matched

    def _matches(self, path: str) -> bool:
        return self._filter.lower() in path.lower()

    def add_password(self, backend: BackendEntries, path: str) -> PasswordNode | None:
        """Add one entry to a backend's listing.

        A convenience over :meth:`sync_entries`, which is where the work
        happens: adding is listing everything that was there plus one more.
        There is one way into the tree rather than two, because two of them
        disagreed about the order rows were kept in, and a reconciliation that
        cannot find a row it is looking for inserts a second one.

        Args:
            backend: Record returned by :meth:`add_backend`
            path: Full entry path, ``work/mail`` style

        Returns:
            The leaf node for the entry, or None when a filter is on and the
            entry does not match it. The entry is remembered either way, so
            clearing the filter brings it back.
        """
        entries = list(backend.entries)
        if path not in entries:
            entries.append(path)
        self.sync_entries(backend, entries)
        if self._filter:
            if not self._matches(path):
                return None
            # It arrived while a search was running -- a listing coming back
            # late, or an entry just saved -- so open the way down to it.
            self.expand_all()
        return self.find(backend.backend_id, path)

    def find(self, backend_id: str, path: str) -> PasswordNode | None:
        """The node for one entry, or None when nothing is showing it."""
        for record in self._backends:
            if record.backend_id != backend_id or record.node is None:
                continue
            found: PasswordNode | None = record.node
            for part in path.split("/"):
                found = self._child_named(found, part) if found is not None else None
            return found
        return None

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
        """Empty the tree completely.

        Only for teardown -- a configuration change that replaces every
        backend. A listing does not come through here: it reconciles, so that
        the rows it does not change keep everything the view knows about them.
        """
        self._backends.clear()
        self.root.remove_all()

    # -- expansion -----------------------------------------------------------

    def _remember_shape(self) -> None:
        """Note which rows are open and which entry is selected.

        For the one transition that genuinely rearranges the tree: a search.
        Everything else corrects the tree in place and needs none of this.
        """
        self._expanded = self.expansion_state()
        self._selected = self.get_selected_password()

    def expansion_state(self) -> set[tuple[str, str]]:
        """The (backend, path) of every row that is currently open.

        Only rows the model has built can be open, and a row is only built once
        its parent has been -- so an open row's ancestors are all in here too,
        which is what makes this enough to put the tree back as it was.
        """
        state = set()
        for index in range(self.tree_model.get_n_items()):
            row = self.tree_model.get_row(index)
            if row is not None and row.get_expanded():
                node = row.get_item()
                state.add((node.backend_id, node.path))
        return state

    def restore_selection(self) -> None:
        """Point at the entry that was selected before the tree was rebuilt.

        Only rows the model has built can be selected, so this runs after
        restore_expansion: an entry inside a folder that is shut again has no
        row to carry the highlight.

        An entry that is no longer there leaves nothing selected, which is the
        truth -- something else has to decide what the detail pane does about
        an entry that has been deleted underneath it.
        """
        if self._selected is None:
            return
        for index in range(self.tree_model.get_n_items()):
            row = self.tree_model.get_row(index)
            node = row.get_item() if row is not None else None
            if node is not None and (node.backend_id, node.password_name) == (
                self._selected
            ):
                self._restoring = True
                try:
                    self.selection.set_selected(index)
                finally:
                    self._restoring = False
                return

    def restore_expansion(self) -> None:
        """Put the tree back into the shape noted by _remember_shape.

        Exactly that shape: rows it names are opened, and rows it does not are
        closed again. Opening alone would leave a cleared search with every
        folder the search had opened still hanging open, which is not where the
        user left the tree.

        Rows that no longer exist are simply not found.
        """
        index = 0
        while index < self.tree_model.get_n_items():
            row = self.tree_model.get_row(index)
            if row is not None:
                node = row.get_item()
                row.set_expanded((node.backend_id, node.path) in self._expanded)
            index += 1

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

    def expand_folders(self) -> None:
        """Show the shape of the store without showing what is in it.

        GTK offers nothing for this. ``Gtk.TreeListModel:autoexpand`` is
        everything or nothing -- and it holds rows open, so a row the user
        closes springs back -- there is no depth limit, and GTK3's
        ``expand_row(open_all=FALSE)`` has no successor. What there is is
        ``Gtk.TreeListRow.set_expanded`` per row, which is enough: the
        application knows which rows are folders and can say so one at a time.

        A folder is opened when it holds another folder, so the directories
        below it are reachable; one that holds only entries stays shut, because
        opening it is exactly what this is for avoiding. An entry sitting
        beside a folder is shown with it -- they are siblings, and there is no
        opening one without the other.
        """
        self._expand(
            lambda row: row.get_depth() == 0 or _holds_a_folder(row.get_item())
        )

    def collapse_all(self) -> None:
        """Shut every row that is open."""
        for index in range(self.tree_model.get_n_items()):
            row = self.tree_model.get_row(index)
            if row is not None:
                row.set_expanded(False)

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
