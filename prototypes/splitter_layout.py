from PySide6 import QtWidgets, QtCore, QtGui
import json
import shiboken6

# ---------- Collapsible handle ----------
class CustomSplitterHandle(QtWidgets.QSplitterHandle):
    def mouseDoubleClickEvent(self, event):
        sp = self.parentWidget()
        if isinstance(sp, CustomSplitter):
            idx = sp.indexOf(self) - 1  # handle i sits after widget i-1
            if idx >= 0:
                sp.toggleCollapse(idx)
        super().mouseDoubleClickEvent(event)

class CustomSplitter(QtWidgets.QSplitter):
    def __init__(self, orientation=QtCore.Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setChildrenCollapsible(True)
        self._saved_sizes = {}

    def createHandle(self):
        return CustomSplitterHandle(self.orientation(), self)

    def toggleCollapse(self, index: int):
        sizes = self.sizes()
        if not (0 <= index < len(sizes)):
            return
        if sizes[index] > 0:
            self._saved_sizes[index] = sizes[index]
            sizes[index] = 0
            self.setSizes(sizes)
        else:
            cur = self.sizes()
            saved = self._saved_sizes.get(index)
            if not saved:
                total = sum(cur)
                saved = max(1, total // max(1, len(cur)))
            cur[index] = saved
            self.setSizes(cur)

# ---------- Layout container ----------
class SplitterLayoutWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.root_splitter: CustomSplitter | None = None
        self._widgets: list[QtWidgets.QWidget] = []
        self._widget_refs: dict[str, QtWidgets.QWidget] = {}  # keep strong refs
        self.edit_mode = False
        self._drag_start_pos = QtCore.QPoint()

    # ---------- public API ----------
    def set_edit_mode(self, enabled: bool):
        self.edit_mode = enabled

    def add_widget(self, widget: QtWidgets.QWidget,
                   target: QtWidgets.QWidget | None = None,
                   position: str | None = None):
        """position in {'left','right','top','bottom'} relative to target"""
        # 0) prepare & keep strong ref BEFORE inserting anywhere
        self._prepare_widget(widget)
        self._remember(widget)

        if self.root_splitter is None:
            self.root_splitter = CustomSplitter(QtCore.Qt.Horizontal)
            self._layout.addWidget(self.root_splitter)
            self.root_splitter.addWidget(widget)
            return

        if target and position:
            self._insert_widget_in_layout(widget, target, position)
        else:
            self.root_splitter.addWidget(widget)

    def save_layout_json(self) -> str:
        data = self._serialize(self.root_splitter if self.root_splitter else (self._widgets[0] if self._widgets else None))
        return json.dumps(data, ensure_ascii=False)

    def load_layout_json(self, s: str, widget_map: dict[str, QtWidgets.QWidget] | None = None):
        data = json.loads(s)
        self.load_layout(data, widget_map)

    # ---------- internals ----------
    def _prepare_widget(self, w: QtWidgets.QWidget):
        if not w.objectName():
            w.setObjectName(f"widget_{len(self._widgets) + 1}")
        if shiboken6.isValid(w):
            # set these BEFORE inserting to avoid touching possibly-deleted obj later
            w.setAcceptDrops(True)
            w.installEventFilter(self)
        if w not in self._widgets:
            self._widgets.append(w)

    def _remember(self, w: QtWidgets.QWidget):
        self._widget_refs[w.objectName()] = w  # strong ref

    def _insert_widget_in_layout(self, widget, target_widget, position, forced_orientation=None):
        # Decide required orientation
        required = QtCore.Qt.Horizontal if position in ("left", "right") else QtCore.Qt.Vertical
        if forced_orientation is not None:
            required = forced_orientation

        parent_splitter = target_widget.parentWidget() if isinstance(target_widget.parentWidget(), QtWidgets.QSplitter) else None
        # Case 1: need a new nested splitter (or target is root without suitable splitter)
        if (parent_splitter is None) or (parent_splitter.orientation() != required):
            new_splitter = CustomSplitter(required)

            if parent_splitter:
                # replace target with new_splitter but avoid immediate deletion:
                idx = parent_splitter.indexOf(target_widget)
                parent_splitter.insertWidget(idx, new_splitter)
                target_widget.setParent(None)  # detach safely
            else:
                # target was at root
                old_root = self.root_splitter
                # add new first to layout to ensure it's parented and alive
                self.root_splitter = new_splitter
                self._layout.addWidget(self.root_splitter)
                if old_root is not None:
                    old_root.setParent(None)

            # order in the new splitter
            if position in ("left", "top"):
                new_splitter.addWidget(widget)
                new_splitter.addWidget(target_widget)
            else:
                new_splitter.addWidget(target_widget)
                new_splitter.addWidget(widget)
            new_splitter.setSizes([1, 1])
        else:
            # Case 2: insert into existing compatible splitter
            idx = parent_splitter.indexOf(target_widget)
            if position in ("left", "top"):
                parent_splitter.insertWidget(idx, widget)
            else:
                parent_splitter.insertWidget(idx + 1, widget)
            parent_splitter.setSizes([1] * parent_splitter.count())

    # ---------- drag & drop ----------
    def eventFilter(self, obj, event):
        if obj in self._widgets:
            t = event.type()
            if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                self._drag_start_pos = event.position().toPoint()
            elif t == QtCore.QEvent.MouseMove and (event.buttons() & QtCore.Qt.LeftButton):
                if self.edit_mode and (event.position().toPoint() - self._drag_start_pos).manhattanLength() > QtWidgets.QApplication.startDragDistance():
                    self._start_drag(obj)
                    return True
            elif t == QtCore.QEvent.DragEnter:
                if self.edit_mode and event.mimeData().hasFormat("application/x-qsplitter-widget"):
                    src = event.source()
                    if src in self._widgets and src is not obj:
                        event.acceptProposedAction()
                        return True
            elif t == QtCore.QEvent.DragMove:
                if self.edit_mode and event.mimeData().hasFormat("application/x-qsplitter-widget"):
                    event.acceptProposedAction()
                    return True
            elif t == QtCore.QEvent.Drop:
                if self.edit_mode and event.mimeData().hasFormat("application/x-qsplitter-widget"):
                    src = event.source()
                    if src in self._widgets and src is not obj:
                        side = self._drop_side(obj, event.position().toPoint())
                        self._insert_widget_in_layout(src, obj, side)
                        if shiboken6.isValid(src):
                            src.show()
                        event.acceptProposedAction()
                        return True
                    else:
                        if shiboken6.isValid(obj):
                            obj.show()
                        event.ignore()
                        return True
        return super().eventFilter(obj, event)

    def _start_drag(self, w: QtWidgets.QWidget):
        if not shiboken6.isValid(w):
            return
        drag = QtGui.QDrag(w)
        mime = QtCore.QMimeData()
        mime.setData("application/x-qsplitter-widget", b"1")
        drag.setMimeData(mime)
        pm = w.grab()
        if not pm.isNull():
            if max(pm.width(), pm.height()) > 150:
                pm = pm.scaled(150, 150, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            drag.setPixmap(pm)
            drag.setHotSpot(QtCore.QPoint(pm.width() // 2, pm.height() // 2))
        w.hide()
        res = drag.exec(QtCore.Qt.MoveAction)
        if res != QtCore.Qt.MoveAction and shiboken6.isValid(w):
            w.show()

    def _drop_side(self, target: QtWidgets.QWidget, pos: QtCore.QPoint) -> str:
        # relative to target center
        cx, cy = target.width() / 2, target.height() / 2
        dx, dy = pos.x() - cx, pos.y() - cy
        if abs(dx) > abs(dy):
            return "left" if dx < 0 else "right"
        else:
            return "top" if dy < 0 else "bottom"

    # ---------- serialization ----------
    def _serialize(self, node):
        if isinstance(node, QtWidgets.QSplitter):
            return {
                "type": "splitter",
                "orientation": "horizontal" if node.orientation() == QtCore.Qt.Horizontal else "vertical",
                "sizes": node.sizes(),
                "children": [self._serialize(node.widget(i)) for i in range(node.count())],
            }
        elif isinstance(node, QtWidgets.QWidget) and node is not None:
            return {"type": "widget", "id": node.objectName(), "collapsed": (not node.isVisible())}
        return {}

    def load_layout(self, layout_data: dict, widget_map: dict[str, QtWidgets.QWidget] | None = None):
        # clear current
        if self.root_splitter:
            self.root_splitter.setParent(None)
            self.root_splitter = None
        for w in list(self._widgets):
            w.setParent(None)
        self._widgets.clear()
        self._widget_refs.clear()

        def build(node):
            t = node.get("type")
            if t == "splitter":
                sp = CustomSplitter(QtCore.Qt.Horizontal if node.get("orientation") == "horizontal" else QtCore.Qt.Vertical)
                for ch in node.get("children", []):
                    w = build(ch)
                    sp.addWidget(w)
                sizes = node.get("sizes")
                if sizes:
                    sp.setSizes([int(s) for s in sizes])
                return sp
            elif t == "widget":
                wid = node.get("id")
                w = widget_map.get(wid) if widget_map else None
                if w is None:
                    w = QtWidgets.QLabel(wid)
                    w.setAlignment(QtCore.Qt.AlignCenter)
                w.setObjectName(wid or f"widget_{len(self._widgets) + 1}")
                if node.get("collapsed"):
                    w.hide()
                self._prepare_widget(w)
                self._remember(w)
                return w
            return QtWidgets.QLabel("Invalid")

        root = build(layout_data)
        if isinstance(root, QtWidgets.QSplitter):
            self.root_splitter = root
            self._layout.addWidget(root)
        else:
            self._layout.addWidget(root)

# --------- Demo ---------
if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    win = QtWidgets.QMainWindow()
    lay = SplitterLayoutWidget()
    win.setCentralWidget(lay)

    def mk_lbl(name, color):
        lbl = QtWidgets.QPushButton(name)
        lbl.setObjectName(name)
        lbl.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        lbl.clicked.connect(lambda: print(f"CLICKED: {name}"))
        lbl.setMinimumSize(120, 90)
        return lbl

    a = mk_lbl("panel1", "#000000")
    b = mk_lbl("panel2", "#000000")
    c = mk_lbl("panel3", "#585858")
    d = mk_lbl("panel4", "#585858")
    e = mk_lbl("panel5", "#585858")

    lay.add_widget(a)
    lay.add_widget(b)
    # ↓ ここで bottom に入れてもクラッシュしない
    lay.add_widget(c, target=a, position="bottom")
    lay.add_widget(d)
    lay.add_widget(e)

    lay.set_edit_mode(True)
    win.resize(900, 600)
    win.show()
    import sys
    sys.exit(app.exec())
