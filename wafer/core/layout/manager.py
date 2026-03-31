from __future__ import annotations

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
    remove_panel,
)

MODE_EDIT = "edit"
MODE_LOCKED = "locked"


@dataclass
class PanelEntry:
    name: str
    widget: QtWidgets.QWidget
    title: str
    default_area: QtCore.Qt.DockWidgetArea = QtCore.Qt.LeftDockWidgetArea
    dock_widget: PanelDockWidget | None = None
    floating_window: FloatingWindow | None = None


class LayoutManager(QtCore.QObject):
    mode_changed = QtCore.Signal(str)

    def __init__(self, window: QtWidgets.QMainWindow, parent=None):
        super().__init__(parent or window)
        self._window = window
        self._panels: dict[str, PanelEntry] = {}
        self._mode = MODE_LOCKED
        self._tree = LayoutTree()
        self._root_splitter: QtWidgets.QSplitter | None = None
        self._central_placeholder: QtWidgets.QWidget | None = None
        self._window.setDockOptions(
            QtWidgets.QMainWindow.AnimatedDocks
            | QtWidgets.QMainWindow.AllowNestedDocks
        )

    @property
    def mode(self) -> str:
        return self._mode

    def register(
        self,
        name: str,
        widget: QtWidgets.QWidget,
        title: str,
        *,
        floating: bool = True,
        default_area: QtCore.Qt.DockWidgetArea = QtCore.Qt.LeftDockWidgetArea,
    ) -> PanelEntry:
        entry = PanelEntry(
            name=name,
            widget=widget,
            title=title,
            default_area=default_area,
        )
        self._panels[name] = entry

        if floating:
            existing = self._tree.floating.get(name)
            self._make_floating(entry, existing)
        else:
            self._tree.root = insert_panel(self._tree.root, name)
            self._rebuild()
        return entry

    def unregister(self, name: str):
        entry = self._panels.pop(name, None)
        if entry is None:
            return
        self._cleanup_entry(entry)
        self._tree.root = remove_panel(self._tree.root, name)
        self._tree.floating.pop(name, None)
        self._tree.hidden.discard(name)
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

        if name in self._tree.hidden:
            self._tree.hidden.discard(name)
            if name in self._tree.floating:
                self._make_floating(entry, self._tree.floating[name])
            elif self._mode == MODE_EDIT and entry.dock_widget:
                entry.dock_widget.show()
            else:
                self._rebuild()
        else:
            self._tree.hidden.add(name)
            if entry.floating_window:
                entry.floating_window.hide()
            elif self._mode == MODE_EDIT and entry.dock_widget:
                entry.dock_widget.hide()
            else:
                self._rebuild()

    def float_panel(self, name: str):
        entry = self._panels.get(name)
        if entry is None:
            return
        if self._is_floating(entry):
            return

        geo = entry.widget.geometry()
        global_pos = entry.widget.mapToGlobal(QtCore.QPoint(0, 0))
        fs = FloatingState(global_pos.x(), global_pos.y(), geo.width(), geo.height())

        if name in self._tree.docked_names():
            self._detach_from_dock_or_splitter(entry)
            self._tree.root = remove_panel(self._tree.root, name)

        self._tree.floating[name] = fs
        self._make_floating(entry, fs)
        self._rebuild()

    def dock_panel(self, name: str):
        entry = self._panels.get(name)
        if entry is None:
            return
        if not self._is_floating(entry):
            return

        self._take_back_from_floating(entry)
        self._tree.floating.pop(name, None)
        self._tree.root = insert_panel(self._tree.root, name)
        self._rebuild()

    def is_panel_visible(self, name: str) -> bool:
        return name not in self._tree.hidden

    def panel_names(self) -> list[str]:
        return list(self._panels.keys())

    def save_state(self) -> dict:
        self._sync_tree_from_current()
        return {
            'mode': self._mode,
            'tree': self._tree.to_dict(),
        }

    def restore_state(self, state: dict):
        tree_data = state.get('tree')
        if tree_data:
            self._tree = LayoutTree.from_dict(tree_data)

        for entry in self._panels.values():
            self._cleanup_entry(entry)
            entry.widget.setParent(None)
        if self._root_splitter:
            self._root_splitter.setParent(None)
            self._root_splitter.deleteLater()
            self._root_splitter = None
        self._remove_central_placeholder()

        target_mode = state.get('mode', MODE_LOCKED)
        self._mode = target_mode
        if target_mode == MODE_EDIT:
            self._build_edit_layout()
        else:
            self._build_locked_layout()
            for name, fs in self._tree.floating.items():
                entry = self._panels.get(name)
                if entry and not self._is_floating(entry) and name not in self._tree.hidden:
                    self._show_as_independent_window(entry, fs)

    def _to_edit_mode(self):
        self._sync_tree_from_current()

        floating_states: dict[str, FloatingState] = {}
        for name, entry in self._panels.items():
            if entry.floating_window:
                floating_states[name] = capture_floating_state(entry.floating_window)
                self._take_back_from_floating(entry)

        if self._root_splitter:
            self._detach_all_from_splitter()
            self._root_splitter.setParent(None)
            self._root_splitter.deleteLater()
            self._root_splitter = None

        self._build_edit_layout(floating_states)

    def _to_locked_mode(self):
        self._sync_tree_from_current()

        floating_states: dict[str, FloatingState] = {}
        for name in list(self._tree.floating):
            entry = self._panels.get(name)
            if not entry:
                continue
            fs = self._tree.floating[name]
            floating_states[name] = fs

        for name, entry in self._panels.items():
            if entry.dock_widget:
                entry.dock_widget.setWidget(None)
                entry.widget.setParent(None)
                entry.dock_widget.setParent(None)
                entry.dock_widget.deleteLater()
                entry.dock_widget = None

        self._remove_central_placeholder()
        self._build_locked_layout()

        for name, fs in floating_states.items():
            entry = self._panels.get(name)
            if entry and not self._is_floating(entry) and name not in self._tree.hidden:
                self._show_as_independent_window(entry, fs)

    def _build_edit_layout(self, floating_overrides: dict[str, FloatingState] | None = None):
        self._ensure_central_placeholder()
        floating_names = set(self._tree.floating.keys())

        for name, entry in self._panels.items():
            if name in self._tree.hidden:
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
            if name in self._tree.hidden:
                continue
            entry = self._panels.get(name)
            if entry:
                visible_widgets[name] = entry.widget

        splitter = build_splitter(self._tree.root, visible_widgets)
        if isinstance(splitter, QtWidgets.QSplitter):
            self._root_splitter = splitter
        elif isinstance(splitter, QtWidgets.QWidget):
            self._root_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
            splitter.setParent(self._root_splitter)
            self._root_splitter.addWidget(splitter)
        else:
            return
        self._window.setCentralWidget(self._root_splitter)

    def _rebuild(self):
        if self._mode == MODE_LOCKED:
            if self._root_splitter:
                self._detach_all_from_splitter()
                self._root_splitter.setParent(None)
                self._root_splitter.deleteLater()
                self._root_splitter = None
            self._build_locked_layout()

    def _sync_tree_from_current(self):
        if self._mode == MODE_LOCKED and self._root_splitter:
            splitters = collect_splitters(self._root_splitter)
            if self._tree.root and isinstance(self._tree.root, SplitNode):
                snapshot_sizes(self._tree.root, splitters, [0])
        elif self._mode == MODE_EDIT:
            docked_docks: dict[str, PanelDockWidget] = {}
            for name, entry in self._panels.items():
                if entry.dock_widget and not entry.dock_widget.isFloating() and name not in self._tree.hidden:
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
                geo = entry.dock_widget.geometry()
                self._tree.floating[name] = FloatingState(
                    geo.x(), geo.y(), geo.width(), geo.height(),
                )

    def _arrange_docks_from_tree(self):
        if self._tree.root is None:
            return
        self._split_node_recursive(self._tree.root)

        for name, entry in self._panels.items():
            if entry.dock_widget and name not in self._tree.hidden:
                if not entry.dock_widget.isVisible() and not entry.dock_widget.isFloating():
                    entry.dock_widget.show()

    def _split_node_recursive(self, node: SplitNode | LeafNode):
        if isinstance(node, LeafNode):
            return

        qt_orient = (
            QtCore.Qt.Horizontal
            if node.orientation == Orientation.HORIZONTAL
            else QtCore.Qt.Vertical
        )

        child_docks: list[PanelDockWidget] = []
        child_sizes: list[int] = []
        for i, child in enumerate(node.children):
            dock = self._first_visible_dock(child)
            if dock:
                child_docks.append(dock)
                size = node.sizes[i] if i < len(node.sizes) else 200
                child_sizes.append(max(size, 1))

        for i in range(1, len(child_docks)):
            self._window.splitDockWidget(child_docks[i - 1], child_docks[i], qt_orient)

        if len(child_docks) > 1 and child_sizes:
            QtWidgets.QApplication.processEvents()
            self._window.resizeDocks(child_docks, child_sizes, qt_orient)

        for child in node.children:
            if isinstance(child, SplitNode):
                self._split_node_recursive(child)

    def _first_visible_dock(self, node: SplitNode | LeafNode) -> PanelDockWidget | None:
        if isinstance(node, LeafNode):
            if node.panel_name in self._tree.hidden:
                return None
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
        dock = create_dock(
            entry.name, entry.title, entry.widget, self._window, entry.default_area,
        )
        dock.closed.connect(self._on_dock_closed)
        dock.topLevelChanged.connect(
            lambda floating, n=entry.name: self._on_dock_float_changed(n, floating))
        entry.dock_widget = dock
        return dock

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

        if entry.floating_window:
            self._take_back_from_floating(entry)

        dock = self._create_managed_dock(entry)
        dock.setFloating(True)
        if state:
            dock.setGeometry(state.x, state.y, state.width, state.height)
        if entry.name in self._tree.hidden:
            dock.hide()

    def _show_as_independent_window(self, entry: PanelEntry, state: FloatingState | None = None):
        if entry.floating_window:
            return

        if entry.dock_widget:
            entry.dock_widget.setWidget(None)
            entry.widget.setParent(None)
            entry.dock_widget.setParent(None)
            entry.dock_widget.deleteLater()
            entry.dock_widget = None

        win = apply_floating(entry.name, entry.title, entry.widget, state)
        win.closed.connect(self._on_floating_closed)
        entry.floating_window = win
        self._tree.floating[entry.name] = state or FloatingState(
            win.x(), win.y(), win.width(), win.height(),
        )

        if entry.name in self._tree.hidden:
            win.hide()

    def _take_back_from_floating(self, entry: PanelEntry):
        if entry.floating_window:
            fs = capture_floating_state(entry.floating_window)
            self._tree.floating[entry.name] = fs
            w = entry.floating_window.take_widget()
            win = entry.floating_window
            entry.floating_window = None
            win.close()
            if w:
                entry.widget = w
        elif entry.dock_widget and entry.dock_widget.isFloating():
            geo = entry.dock_widget.geometry()
            self._tree.floating[entry.name] = FloatingState(
                geo.x(), geo.y(), geo.width(), geo.height(),
            )
            entry.dock_widget.setFloating(False)

    def _detach_from_dock_or_splitter(self, entry: PanelEntry):
        if entry.dock_widget:
            entry.dock_widget.setWidget(None)
            entry.widget.setParent(None)
            self._window.removeDockWidget(entry.dock_widget)
            entry.dock_widget.deleteLater()
            entry.dock_widget = None
        else:
            entry.widget.setParent(None)

    def _detach_all_from_splitter(self):
        for name, entry in self._panels.items():
            if entry.floating_window is None and entry.dock_widget is None:
                entry.widget.setParent(None)

    def _cleanup_entry(self, entry: PanelEntry):
        if entry.floating_window:
            win = entry.floating_window
            entry.floating_window = None
            win.close()
        if entry.dock_widget:
            dock = entry.dock_widget
            entry.dock_widget = None
            self._window.removeDockWidget(dock)
            dock.deleteLater()

    def _ensure_central_placeholder(self):
        if self._central_placeholder is None:
            self._central_placeholder = QtWidgets.QWidget()
            self._central_placeholder.setMaximumSize(0, 0)
        self._window.setCentralWidget(self._central_placeholder)

    def _remove_central_placeholder(self):
        if self._central_placeholder:
            self._central_placeholder.setParent(None)
            self._central_placeholder.deleteLater()
            self._central_placeholder = None

    def _on_dock_closed(self, name: str):
        self._tree.hidden.add(name)

    def _on_dock_float_changed(self, name: str, floating: bool):
        if floating:
            entry = self._panels.get(name)
            if entry and entry.dock_widget:
                geo = entry.dock_widget.geometry()
                self._tree.floating[name] = FloatingState(
                    geo.x(), geo.y(), geo.width(), geo.height(),
                )
        else:
            self._tree.floating.pop(name, None)

    def _on_floating_closed(self, name: str):
        entry = self._panels.get(name)
        if not entry or not entry.floating_window:
            return
        self._tree.floating[name] = capture_floating_state(entry.floating_window)
        self._tree.hidden.add(name)
