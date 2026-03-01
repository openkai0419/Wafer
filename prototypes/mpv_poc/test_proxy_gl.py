import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['PATH'] = SCRIPT_DIR + os.pathsep + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(SCRIPT_DIR)

import mpv

from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtOpenGLWidgets import QOpenGLWidget


def _get_proc_address(_, name):
    from PySide6.QtGui import QOpenGLContext
    ctx = QOpenGLContext.currentContext()
    if ctx is None:
        return 0
    addr = ctx.getProcAddress(name)
    return int(addr) if addr else 0


_get_proc_address_c = mpv.MpvGlGetProcAddressFn(_get_proc_address)


PREVIEW_VOLUME = 40


class MpvCellWidget(QOpenGLWidget):

    _on_update = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.player: mpv.MPV | None = None
        self._ctx: mpv.MpvRenderContext | None = None
        self._frame_ready = False
        self._path: str | None = None
        self._playing = False
        self._on_update.connect(self._request_update, Qt.ConnectionType.QueuedConnection)

    def initializeGL(self):
        self.player = mpv.MPV(
            vo='libmpv',
            hwdec='auto',
            keep_open='yes',
            idle='yes',
            loop='inf',
        )
        self.player.volume = PREVIEW_VOLUME
        self._ctx = mpv.MpvRenderContext(
            self.player, 'opengl',
            opengl_init_params={'get_proc_address': _get_proc_address_c},
        )
        self._ctx.update_cb = self._on_mpv_frame
        if self._path:
            self.player.pause = True
            self.player.play(self._path)

    def _on_mpv_frame(self):
        self._frame_ready = True
        self._on_update.emit()

    @Slot()
    def _request_update(self):
        if self._frame_ready and self.isVisible():
            self.update()

    def paintGL(self):
        if self._ctx is None:
            return
        self._frame_ready = False
        ratio = self.devicePixelRatioF()
        w = int(self.width() * ratio)
        h = int(self.height() * ratio)
        fbo = self.defaultFramebufferObject()
        self._ctx.render(
            opengl_fbo={'w': w, 'h': h, 'fbo': fbo},
            flip_y=True,
        )

    def load(self, path):
        self._path = path
        self._playing = False
        if self.player:
            self.player.pause = True
            self.player.play(path)

    def enterEvent(self, event):
        super().enterEvent(event)
        if self._path and self.player and not self._playing:
            self._playing = True
            self.player.pause = False

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._playing and self.player:
            self._playing = False
            self.player.pause = True
            try:
                self.player.seek(0, 'absolute')
            except SystemError:
                pass

    def cleanup(self):
        self._playing = False
        if self._ctx:
            self._ctx.free()
            self._ctx = None
        if self.player:
            self.player.terminate()
            self.player = None


class FakeGridView(QtWidgets.QGraphicsView):

    COLS = 2
    SPACING = 4
    VIDEO_INDICES = {0, 4, 7, 13}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.MinimalViewportUpdate)
        self.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing
            | QtGui.QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QtGui.QColor(30, 30, 30))

        self._n_items = 40
        self._base_height = 160
        self._min_height = 50
        self._max_height = 800

        self._item_rects: dict[int, QtCore.QRect] = {}
        self._scene_items: dict[int, QtWidgets.QGraphicsRectItem] = {}

        self._gl_widgets: dict[int, MpvCellWidget] = {}
        self._video_path: str | None = None
        self._next_video_idx = 0

        self.verticalScrollBar().valueChanged.connect(self._sync_overlays)
        self.horizontalScrollBar().valueChanged.connect(self._sync_overlays)

    def _recalc_layout(self):
        vw = max(self.viewport().width(), 1)
        cols = self.COLS
        sp = self.SPACING
        cell_w = (vw - sp * (cols - 1)) // cols
        cell_h = self._base_height

        self._item_rects.clear()
        for i in range(self._n_items):
            col = i % cols
            row = i // cols
            x = col * (cell_w + sp)
            y = row * (cell_h + sp)
            self._item_rects[i] = QtCore.QRect(x, y, cell_w, cell_h)

        for item in self._scene_items.values():
            self._scene.removeItem(item)
        self._scene_items.clear()

        for i, rect in self._item_rects.items():
            if i in self._gl_widgets:
                pen = QtGui.QPen(QtGui.QColor(0, 200, 0))
                brush = QtGui.QBrush(QtGui.QColor(20, 40, 20))
            else:
                pen = QtGui.QPen(QtGui.QColor(50, 50, 50))
                brush = QtGui.QBrush(QtGui.QColor(40, 40, 40))
            ri = self._scene.addRect(rect.x(), rect.y(), rect.width(), rect.height(), pen, brush)
            self._scene_items[i] = ri

            label = self._scene.addSimpleText(str(i), QtGui.QFont('Consolas', 8))
            label.setBrush(QtGui.QColor(120, 120, 120))
            label.setPos(rect.x() + 4, rect.y() + 4)

        last = self._item_rects.get(self._n_items - 1)
        if last:
            total_h = last.y() + last.height()
            self._scene.setSceneRect(0, 0, vw, total_h)

        self._sync_overlays()

    def _sync_overlays(self):
        vp_rect = self.viewport().rect()
        for idx, widget in self._gl_widgets.items():
            scene_rect = self._item_rects.get(idx)
            if scene_rect is None:
                widget.hide()
                continue
            vp_point = self.mapFromScene(
                QtCore.QPointF(scene_rect.x(), scene_rect.y())
            )
            mapped = QtCore.QRect(
                int(vp_point.x()), int(vp_point.y()),
                scene_rect.width(), scene_rect.height(),
            )
            if mapped.intersects(vp_rect):
                widget.setGeometry(mapped)
                widget.show()
            else:
                widget.hide()

    def add_video_widget(self):
        idx = self._next_video_idx
        self._next_video_idx += 1
        w = MpvCellWidget(self.viewport())
        w.hide()
        self._gl_widgets[idx] = w
        if self._video_path:
            w.load(self._video_path)
        self._sync_overlays()
        return idx

    def set_video(self, path):
        self._video_path = path
        for w in self._gl_widgets.values():
            w.load(path)
        self._sync_overlays()

    def _change_base_height(self, delta):
        new = max(self._min_height, min(self._max_height, self._base_height + delta))
        if new != self._base_height:
            self._base_height = new
            self._recalc_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalc_layout()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            self._change_base_height(20 if delta > 0 else -20)
            event.accept()
        else:
            super().wheelEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._recalc_layout)

    def cleanup(self):
        for w in self._gl_widgets.values():
            w.cleanup()


class TestWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Test: QOpenGLWidget on GridView-like QGraphicsView')
        self.resize(900, 650)

        self._grid = FakeGridView()
        self.setCentralWidget(self._grid)

        menu = self.menuBar().addMenu('File')
        act = QtGui.QAction('Open video...', self)
        act.setShortcut('Ctrl+O')
        act.triggered.connect(self._open)
        menu.addAction(act)

        add_act = QtGui.QAction('Add widget', self)
        add_act.setShortcut('Ctrl+A')
        add_act.triggered.connect(self._add_widget)
        menu.addAction(add_act)

        self._status = QtWidgets.QLabel(
            'Ctrl+O: open | Ctrl+A: add widget | Hover to play | Ctrl+Wheel: zoom'
        )
        self._status.setStyleSheet(
            'color: #0f0; background: #1a1a1a; padding: 4px; font: bold 11px Consolas;'
        )
        self.statusBar().addWidget(self._status, 1)

    def _open(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open Video', '',
            'Video (*.mp4 *.mkv *.webm *.avi *.mov *.wmv *.flv);;All (*)',
        )
        if not path:
            return
        self._status.setText(f'Playing: {os.path.basename(path)}')
        self._grid.set_video(path)

    def _add_widget(self):
        idx = self._grid.add_video_widget()
        count = len(self._grid._gl_widgets)
        self._status.setText(f'Added widget at cell {idx} (total: {count})')

    def closeEvent(self, event):
        self._grid.cleanup()
        super().closeEvent(event)


def main():
    QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication(sys.argv)
    win = TestWindow()
    win.show()
    if len(sys.argv) > 1:
        for w in win._widgets:
            w.load(sys.argv[1])
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
