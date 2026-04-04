from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6 import QtCore, QtWidgets

from .dock import (
    FloatingWindow,
    PanelDockWidget,
    apply_floating,
    capture_floating_state,
    create_dock,
)
from .inference import infer_tree
from .splitter import build_splitter, collect_splitters, snapshot_sizes
from .tree import (
    FloatingState,
    LayoutTree,
    LeafNode,
    Orientation,
    SplitNode,
    flatten,
    insert_panel,
    normalize_sizes,
    reinsert_from_blueprint,
    remove_panel,
)

MODE_EDIT = "edit"
MODE_LOCKED = "locked"


@dataclass
class PanelEntry:
    name: str
    factory: Callable[[], QtWidgets.QWidget]
    closable: bool = True
    widget: QtWidgets.QWidget | None = None
    dock_widget: PanelDockWidget | None = None
    floating_window: FloatingWindow | None = None
    last_floating: FloatingState | None = None

    def has_visible_presence(self) -> bool:
        return self.floating_window is not None or self.dock_widget is not None


class LayoutManager(QtCore.QObject):
    mode_changed = QtCore.Signal(str)

    def __init__(self, window: QtWidgets.QMainWindow, parent=None):
        super().__init__(parent or window)
        self._window = window
        self._panels: dict[str, PanelEntry] = {}
        self._mode = MODE_LOCKED
        self._tree = LayoutTree()
        self._root_splitter: QtWidgets.QSplitter | None = None
        self._central_container: QtWidgets.QWidget | None = None
        self._central_placeholder = QtWidgets.QWidget()
        self._central_placeholder.setMaximumSize(0, 0)
        self._pending_state: dict | None = None
        self._pending_tree: LayoutTree | None = None
        self._margin = 0
        self._window.setDockOptions(
            QtWidgets.QMainWindow.AnimatedDocks
            | QtWidgets.QMainWindow.AllowNestedDocks
        )

    @property
    def mode(self) -> str:
        return self._mode

    def set_margin(self, margin: int):
        self._margin = margin

    def register(
        self,
        name: str,
        factory: Callable[[], QtWidgets.QWidget],
        *,
        closable: bool = True,
    ) -> PanelEntry:
        if name in self._panels:
            self.unregister(name)
        entry = PanelEntry(name=name, factory=factory, closable=closable)
        self._panels[name] = entry
        self._register_toggle_command(name)
        if self._pending_state is not None:
            self._apply_pending_for(name, entry)
        return entry

    def _ensure_widget(self, entry: PanelEntry) -> QtWidgets.QWidget:
        if entry.widget is None:
            entry.widget = entry.factory()
        return entry.widget

    def unregister(self, name: str):
        entry = self._panels.pop(name, None)
        if entry is None:
            return
        self._unregister_toggle_command(name)
        self._cleanup_entry(entry)
        self._tree.root = remove_panel(self._tree.root, name)
        self._tree.floating.pop(name, None)
        self._tree.collapsed.discard(name)
        self._rebuild()

    def set_mode(self, mode: str):
        if mode == self._mode:
            return
        if mode == MODE_EDIT:
            self._to_edit_mode()
        elif mode == MODE_LOCKED:
            self._to_locked_mode()
        self._mode = mode
        self.mode_changed.emit(mode)

    def toggle_mode(self):
        self.set_mode(MODE_LOCKED if self._mode == MODE_EDIT else MODE_EDIT)

    def toggle_panel(self, name: str):
        entry = self._panels.get(name)
        if entry is None:
            return

        if name not in self._tree.all_names():
            fs = entry.last_floating or self._next_floating_position()
            self._tree.floating[name] = fs
            self._make_floating(entry, fs)
            return

        if name in self._tree.floating:
            if not entry.closable:
                return
            entry.last_floating = capture_floating_state(
                entry.floating_window or entry.dock_widget
            )
            self._cleanup_entry(entry)
            self._tree.floating.pop(name, None)
            return

        if self._mode != MODE_LOCKED:
            self.set_mode(MODE_LOCKED)

        w = entry.widget
        effectively_hidden = (
            name in self._tree.collapsed
            or w is None
            or w.width() <= 0
            or w.height() <= 0
        )
        if effectively_hidden:
            self._tree.collapsed.discard(name)
            normalize_sizes(self._tree.root, self._tree.collapsed)
            self._apply_tree_sizes()
        else:
            self._sync_tree_from_current()
            self._tree.collapsed.add(name)
            self._apply_collapse_state()

    def is_panel_visible(self, name: str) -> bool:
        return name in self._tree.all_names() and name not in self._tree.collapsed

    def is_panel_collapsed(self, name: str) -> bool:
        return name in self._tree.collapsed

    def panel_names(self) -> list[str]:
        return list(self._panels.keys())

    def dormant_panels(self) -> list[str]:
        active = self._tree.all_names()
        return [n for n in self._panels if n not in active]

    def save_state(self) -> dict:
        self._sync_tree_from_current()
        result = {
            'mode': self._mode,
            'tree': self._tree.to_dict(),
        }
        dormant = {}
        active = self._tree.all_names()
        for name, entry in self._panels.items():
            if name not in active:
                fs = entry.last_floating
                dormant[name] = {'x': fs.x, 'y': fs.y, 'width': fs.width, 'height': fs.height} if fs else None
        if dormant:
            result['dormant'] = dormant
        return result

    def restore_state(self, state: dict):
        self._pending_state = state
        self._pending_tree = None
        old_mode = self._mode

        tree_data = state.get('tree')
        if tree_data:
            self._tree = LayoutTree.from_dict(tree_data)

        registered = set(self._panels.keys())
        saved_names = self._tree.all_names()
        saved_dormant = set(state.get('dormant', {}).keys())

        for name in set(self._tree.docked_names()) - registered:
            self._tree.root = remove_panel(self._tree.root, name)
        for name in set(self._tree.floating.keys()) - registered:
            del self._tree.floating[name]
        self._tree.collapsed &= registered & set(self._tree.docked_names())

        for name, fs_dict in state.get('dormant', {}).items():
            entry = self._panels.get(name)
            if entry and fs_dict:
                entry.last_floating = FloatingState(**fs_dict)

        extra_floating: dict[str, FloatingState] = {}
        for name in registered - saved_names - saved_dormant:
            entry = self._panels[name]
            if entry.has_visible_presence():
                source = entry.floating_window or entry.dock_widget
                fs = capture_floating_state(source)
                entry.last_floating = fs
                extra_floating[name] = fs
        self._tree.floating.update(extra_floating)

        old_floating: list[FloatingWindow] = []
        old_docks: list[PanelDockWidget] = []
        for entry in self._panels.values():
            if entry.floating_window:
                old_floating.append(entry.floating_window)
                entry.floating_window = None
            if entry.dock_widget:
                old_docks.append(entry.dock_widget)
                self._disconnect_dock_signals(entry.dock_widget)
                entry.dock_widget = None
        old_splitter = self._root_splitter
        old_container = self._central_container
        self._root_splitter = None
        self._central_container = None
        self._remove_central_placeholder()

        target_mode = state.get('mode', MODE_LOCKED)
        self._mode = target_mode
        self._window.setUpdatesEnabled(False)
        try:
            if target_mode == MODE_EDIT:
                self._build_edit_layout()
            else:
                self._build_locked_layout()
                for name, fs in self._tree.floating.items():
                    entry = self._panels.get(name)
                    if entry and not self._is_floating(entry):
                        self._show_as_independent_window(entry, fs)
        finally:
            self._window.setUpdatesEnabled(True)

        for win in old_floating:
            try:
                win.closed.disconnect()
            except RuntimeError:
                pass
            win.close()
            win.deleteLater()
        for dock in old_docks:
            self._window.removeDockWidget(dock)
            dock.setParent(None)
            dock.deleteLater()
        if old_container:
            old_container.setParent(None)
            old_container.deleteLater()
        elif old_splitter:
            old_splitter.setParent(None)
            old_splitter.deleteLater()

        if old_mode != target_mode:
            self.mode_changed.emit(target_mode)

    def _to_edit_mode(self):
        self._sync_tree_from_current()

        old_splitter = self._root_splitter
        old_container = self._central_container
        self._root_splitter = None
        self._central_container = None

        self._window.setUpdatesEnabled(False)
        try:
            self._build_edit_layout(self._tree.floating)

            for entry in self._panels.values():
                if entry.floating_window:
                    self._discard_floating_shell(entry)

            if old_container:
                old_container.setParent(None)
                old_container.deleteLater()
            elif old_splitter:
                old_splitter.setParent(None)
                old_splitter.deleteLater()
        finally:
            self._window.setUpdatesEnabled(True)

    def _to_locked_mode(self):
        self._sync_tree_from_current()

        floating_states: dict[str, FloatingState] = {}
        for name in list(self._tree.floating):
            entry = self._panels.get(name)
            if not entry:
                continue
            floating_states[name] = self._tree.floating[name]

        self._window.setUpdatesEnabled(False)
        try:
            self._build_locked_layout()

            for name, fs in floating_states.items():
                entry = self._panels.get(name)
                if entry and not entry.floating_window:
                    self._show_as_independent_window(entry, fs)

            for name in list(self._tree.docked_names()):
                entry = self._panels.get(name)
                if entry:
                    self._discard_dock_shell(entry)

            self._remove_central_placeholder()
        finally:
            self._window.setUpdatesEnabled(True)

    def _build_edit_layout(self, floating_overrides: dict[str, FloatingState] | None = None):
        self._ensure_central_placeholder()
        floating_names = set(self._tree.floating.keys())

        for name in list(self._tree.all_names()):
            entry = self._panels.get(name)
            if not entry:
                continue
            dock = self._create_managed_dock(entry)
            if name in floating_names:
                fs = (floating_overrides or {}).get(name) or self._tree.floating.get(name)
                dock.setFloating(True)
                if fs:
                    dock.setGeometry(fs.x, fs.y, fs.width, fs.height)

        self._arrange_docks_from_tree()

    def _build_locked_layout(self):
        if self._tree.root is None:
            return

        visible_widgets = {}
        for name in self._tree.docked_names():
            entry = self._panels.get(name)
            if entry:
                visible_widgets[name] = self._ensure_widget(entry)

        was_enabled = self._window.updatesEnabled()
        if was_enabled:
            self._window.setUpdatesEnabled(False)
        try:
            splitter = build_splitter(self._tree.root, visible_widgets, collapsed=self._tree.collapsed)
            if isinstance(splitter, QtWidgets.QSplitter):
                self._root_splitter = splitter
            elif isinstance(splitter, QtWidgets.QWidget):
                self._root_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
                splitter.setParent(self._root_splitter)
                self._root_splitter.addWidget(splitter)
            else:
                return
            self._set_central(self._root_splitter)
            self._apply_collapse_state()
        finally:
            if was_enabled:
                self._window.setUpdatesEnabled(True)

    def _rebuild(self):
        if self._mode == MODE_LOCKED:
            old_splitter = self._root_splitter
            old_container = self._central_container
            self._root_splitter = None
            self._central_container = None
            self._window.setUpdatesEnabled(False)
            try:
                self._build_locked_layout()
                if old_container:
                    old_container.setParent(None)
                    old_container.deleteLater()
                elif old_splitter:
                    old_splitter.setParent(None)
                    old_splitter.deleteLater()
            finally:
                self._window.setUpdatesEnabled(True)
        elif self._mode == MODE_EDIT:
            for name in self._tree.docked_names():
                entry = self._panels.get(name)
                if entry and not entry.dock_widget:
                    self._create_managed_dock(entry)
            self._arrange_docks_from_tree()

    def _sync_tree_from_current(self):
        if self._mode == MODE_LOCKED and self._root_splitter:
            splitters = collect_splitters(self._root_splitter)
            if self._tree.root and isinstance(self._tree.root, SplitNode):
                snapshot_sizes(self._tree.root, splitters, [0])
        elif self._mode == MODE_EDIT:
            docked_docks: dict[str, PanelDockWidget] = {}
            for name, entry in self._panels.items():
                if entry.dock_widget and not entry.dock_widget.isFloating():
                    docked_docks[name] = entry.dock_widget
            if docked_docks:
                inferred_root, _ = infer_tree(docked_docks, self._window)
                if inferred_root is not None:
                    self._tree.root = flatten(inferred_root)
                    if isinstance(self._tree.root, SplitNode):
                        self._snapshot_dock_sizes(self._tree.root, docked_docks)

        for name, entry in self._panels.items():
            if entry.floating_window:
                self._tree.floating[name] = capture_floating_state(entry.floating_window)
            elif entry.dock_widget and entry.dock_widget.isFloating():
                self._tree.floating[name] = capture_floating_state(entry.dock_widget)

    def _arrange_docks_from_tree(self):
        if self._tree.root is None:
            return
        self._split_node_recursive(self._tree.root)

        for name in self._tree.docked_names():
            entry = self._panels.get(name)
            if entry and entry.dock_widget:
                if not entry.dock_widget.isVisible() and not entry.dock_widget.isFloating():
                    entry.dock_widget.show()

    def _split_node_recursive(self, node: SplitNode | LeafNode):
        if isinstance(node, LeafNode):
            return

        prev_dock: PanelDockWidget | None = None
        child_docks: list[PanelDockWidget] = []
        child_sizes: list[int] = []
        subtrees: list[SplitNode] = []
        for i, child in enumerate(node.children):
            dock = self._first_visible_dock(child)
            if dock:
                if prev_dock is not None:
                    self._window.splitDockWidget(prev_dock, dock, node.orientation.to_qt())
                prev_dock = dock
                child_docks.append(dock)
                size = node.sizes[i] if i < len(node.sizes) else 200
                child_sizes.append(max(size, 1))
            if isinstance(child, SplitNode):
                subtrees.append(child)

        if len(child_docks) > 1 and child_sizes:
            QtWidgets.QApplication.processEvents()
            self._window.resizeDocks(child_docks, child_sizes, node.orientation.to_qt())

        for child in subtrees:
            self._split_node_recursive(child)

    def _first_visible_dock(self, node: SplitNode | LeafNode) -> PanelDockWidget | None:
        if isinstance(node, LeafNode):
            if node.panel_name in self._tree.floating:
                return None
            entry = self._panels.get(node.panel_name)
            if entry and entry.dock_widget and not entry.dock_widget.isFloating():
                return entry.dock_widget
            return None
        for child in node.children:
            result = self._first_visible_dock(child)
            if result:
                return result
        return None

    def _create_managed_dock(self, entry: PanelEntry) -> PanelDockWidget:
        widget = self._ensure_widget(entry)
        dock = create_dock(
            entry.name, widget, self._window, QtCore.Qt.LeftDockWidgetArea,
            closable=entry.closable,
        )
        dock.closed.connect(self._on_dock_closed)
        dock.topLevelChanged.connect(
            lambda floating, n=entry.name: self._on_dock_float_changed(n, floating))
        entry.dock_widget = dock
        return dock

    def _disconnect_dock_signals(self, dock: PanelDockWidget):
        try:
            dock.closed.disconnect()
        except RuntimeError:
            pass
        try:
            dock.topLevelChanged.disconnect()
        except RuntimeError:
            pass

    def _snapshot_dock_sizes(
        self,
        node: SplitNode | LeafNode,
        docks: dict[str, PanelDockWidget],
    ):
        if isinstance(node, LeafNode):
            return
        new_sizes = []
        for child in node.children:
            extent = self._subtree_extent(child, docks, node.orientation)
            new_sizes.append(extent)
        node.sizes = new_sizes
        for child in node.children:
            if isinstance(child, SplitNode):
                self._snapshot_dock_sizes(child, docks)

    def _subtree_extent(
        self,
        node: SplitNode | LeafNode,
        docks: dict[str, PanelDockWidget],
        orientation: Orientation,
    ) -> int:
        if isinstance(node, LeafNode):
            dock = docks.get(node.panel_name)
            if dock and dock.isVisible() and not dock.isFloating():
                return dock.width() if orientation == Orientation.HORIZONTAL else dock.height()
            return 0
        if node.orientation == orientation:
            return sum(
                self._subtree_extent(c, docks, orientation)
                for c in node.children
            )
        extents = [
            self._subtree_extent(c, docks, orientation)
            for c in node.children
        ]
        return max(extents) if extents else 0

    def _is_floating(self, entry: PanelEntry) -> bool:
        if entry.floating_window:
            return True
        if entry.dock_widget and entry.dock_widget.isFloating():
            return True
        return False

    _CASCADE_OFFSET = 30
    _CASCADE_MAX_STEPS = 10

    def _next_floating_position(self) -> FloatingState:
        geo = self._window.geometry()
        n = len(self._tree.floating)
        step = n % self._CASCADE_MAX_STEPS
        cx = geo.x() + geo.width() // 2 - 200 + step * self._CASCADE_OFFSET
        cy = geo.y() + geo.height() // 2 - 150 + step * self._CASCADE_OFFSET
        return FloatingState(cx, cy, 400, 300)

    def _make_floating(self, entry: PanelEntry, state: FloatingState | None = None):
        if self._is_floating(entry):
            return
        if self._mode == MODE_EDIT:
            self._make_floating_dock(entry, state)
        else:
            self._show_as_independent_window(entry, state)

    def _make_floating_dock(self, entry: PanelEntry, state: FloatingState | None = None):
        if entry.dock_widget:
            entry.dock_widget.setFloating(True)
            if state:
                entry.dock_widget.setGeometry(state.x, state.y, state.width, state.height)
            return

        dock = self._create_managed_dock(entry)
        if entry.floating_window:
            self._discard_floating_shell(entry)
        dock.setFloating(True)
        if state:
            dock.setGeometry(state.x, state.y, state.width, state.height)
    def _show_as_independent_window(self, entry: PanelEntry, state: FloatingState | None = None):
        if entry.floating_window:
            return

        win = apply_floating(entry.name, self._ensure_widget(entry), state, self._window)
        if entry.dock_widget:
            self._discard_dock_shell(entry)
        win.closed.connect(self._on_floating_closed)
        entry.floating_window = win
        self._tree.floating[entry.name] = state or capture_floating_state(win)

    def _discard_floating_shell(self, entry: PanelEntry):
        win = entry.floating_window
        if not win:
            return
        entry.floating_window = None
        try:
            win.closed.disconnect()
        except RuntimeError:
            pass
        win.close()
        win.deleteLater()

    def _destroy_dock(self, entry: PanelEntry, *, remove_from_window: bool = False):
        dock = entry.dock_widget
        if dock is None:
            return
        entry.dock_widget = None
        self._disconnect_dock_signals(dock)
        dock.setWidget(None)
        if entry.widget:
            entry.widget.setParent(None)
        if remove_from_window:
            self._window.removeDockWidget(dock)
        else:
            dock.setParent(None)
        dock.deleteLater()

    def _discard_dock_shell(self, entry: PanelEntry):
        dock = entry.dock_widget
        if dock is None:
            return
        entry.dock_widget = None
        self._disconnect_dock_signals(dock)
        self._window.removeDockWidget(dock)
        dock.setParent(None)
        dock.deleteLater()

    def _apply_collapse_state(self):
        if not self._root_splitter or not self._tree.collapsed:
            return
        collapsed_widgets = {
            entry.widget
            for name in self._tree.collapsed
            if (entry := self._panels.get(name)) and name in self._tree.docked_names()
        }
        if collapsed_widgets:
            self._collapse_in_splitter(self._root_splitter, collapsed_widgets)

    def _collapse_in_splitter(
        self, splitter: QtWidgets.QSplitter, collapsed_widgets: set[QtWidgets.QWidget],
    ):
        sizes = splitter.sizes()
        changed = False
        for i in range(splitter.count()):
            child = splitter.widget(i)
            if child in collapsed_widgets:
                sizes[i] = 0
                splitter.setCollapsible(i, True)
                changed = True
            elif isinstance(child, QtWidgets.QSplitter):
                self._collapse_in_splitter(child, collapsed_widgets)
        if changed:
            splitter.setSizes(sizes)

    def _apply_tree_sizes(self):
        if not self._root_splitter or not self._tree.root:
            return
        if isinstance(self._tree.root, SplitNode):
            self._sync_node_to_splitter(self._tree.root, self._root_splitter)

    def _sync_node_to_splitter(
        self, node: SplitNode, splitter: QtWidgets.QSplitter,
    ):
        child_idx = 0
        for child in node.children:
            if child_idx >= splitter.count():
                break
            w = splitter.widget(child_idx)
            if isinstance(child, SplitNode) and isinstance(w, QtWidgets.QSplitter):
                self._sync_node_to_splitter(child, w)
            elif isinstance(child, LeafNode) and child.panel_name not in self._tree.collapsed:
                if not w.isVisible():
                    w.show()
            child_idx += 1
        if node.sizes and len(node.sizes) == splitter.count():
            splitter.setSizes(node.sizes)

    def _cleanup_entry(self, entry: PanelEntry):
        if entry.floating_window:
            win = entry.floating_window
            entry.floating_window = None
            if entry.widget:
                entry.widget.setParent(None)
            try:
                win.closed.disconnect()
            except RuntimeError:
                pass
            win.close()
            win.deleteLater()
        if entry.dock_widget:
            self._destroy_dock(entry, remove_from_window=True)

    def _ensure_central_placeholder(self):
        self._window.setCentralWidget(self._central_placeholder)

    def _remove_central_placeholder(self):
        if self._window.centralWidget() is self._central_placeholder:
            self._central_placeholder.setParent(None)

    def _set_central(self, widget: QtWidgets.QWidget):
        if self._window.centralWidget() is self._central_placeholder:
            self._central_placeholder.setParent(None)
        self._central_container = None
        if self._margin > 0:
            container = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(container)
            m = self._margin
            layout.setContentsMargins(m, m, m, m)
            layout.setSpacing(0)
            widget.setParent(container)
            layout.addWidget(widget)
            self._central_container = container
            self._window.setCentralWidget(container)
        else:
            self._window.setCentralWidget(widget)

    def _on_dock_closed(self, name: str):
        entry = self._panels.get(name)
        if entry and not entry.closable:
            if entry.dock_widget:
                entry.dock_widget.show()
            return
        if entry:
            if entry.dock_widget:
                entry.last_floating = capture_floating_state(entry.dock_widget)
            self._destroy_dock(entry, remove_from_window=True)
        self._tree.root = remove_panel(self._tree.root, name)
        self._tree.floating.pop(name, None)
        self._tree.collapsed.discard(name)

    def _on_dock_float_changed(self, name: str, floating: bool):
        if floating:
            entry = self._panels.get(name)
            if entry and entry.dock_widget:
                self._tree.floating[name] = capture_floating_state(entry.dock_widget)
        else:
            self._tree.floating.pop(name, None)

    def _on_floating_closed(self, name: str):
        entry = self._panels.get(name)
        if not entry or not entry.floating_window:
            return
        if not entry.closable:
            return
        entry.last_floating = capture_floating_state(entry.floating_window)
        self._cleanup_entry(entry)
        self._tree.root = remove_panel(self._tree.root, name)
        self._tree.floating.pop(name, None)

    @staticmethod
    def _command_id(panel_name: str) -> str:
        slug = panel_name.lower().replace(" ", "_")
        return f"panel.toggle_{slug}"

    def _register_toggle_command(self, name: str):
        from ..commands.bridge import Command as BridgeCommand
        from ..commands.command.core import CommandMeta

        cmd_id = self._command_id(name)
        mgr = self

        def _toggle(ctx, _name=name):
            mgr.toggle_panel(_name)

        BridgeCommand.register_commands([
            CommandMeta(
                path=cmd_id,
                id=cmd_id,
                display=f"Toggle {name}",
                func=_toggle,
            ),
        ])

    def _unregister_toggle_command(self, name: str):
        from ..commands.command.core import CommandRegistry

        cmd_id = self._command_id(name)
        registry = CommandRegistry.instance()
        registry._commands.pop(cmd_id, None)



    def _apply_pending_for(self, name: str, entry: PanelEntry):
        state = self._pending_state
        if state is None:
            return

        if self._pending_tree is None:
            tree_data = state.get('tree', {})
            self._pending_tree = LayoutTree.from_dict(tree_data)
        original_tree = self._pending_tree
        dormant_data = state.get('dormant', {})

        if name in original_tree.floating:
            fs = original_tree.floating[name]
            self._tree.floating[name] = fs
            if self._mode == MODE_EDIT:
                self._make_floating_dock(entry, fs)
            else:
                self._show_as_independent_window(entry, fs)
            return

        if name in dormant_data:
            fs_dict = dormant_data[name]
            if fs_dict:
                entry.last_floating = FloatingState(**fs_dict)
            return

        if name in set(original_tree.docked_names()):
            saved_root = original_tree.root
            self._tree.root = reinsert_from_blueprint(
                self._tree.root, saved_root, name
            )
            if name in original_tree.collapsed:
                self._tree.collapsed.add(name)
            self._rebuild()
            return
