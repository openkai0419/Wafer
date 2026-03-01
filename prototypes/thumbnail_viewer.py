import os
import sys
import time

from PySide6 import QtCore, QtGui, QtWidgets
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from afterimages.core.platform.thumbnails import FileThumbnailer


def pil_to_qpixmap(img: Image.Image) -> QtGui.QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "BGRA")
    qimg = QtGui.QImage(data, img.width, img.height, img.width * 4, QtGui.QImage.Format_ARGB32)
    return QtGui.QPixmap.fromImage(qimg.copy())


class ThumbnailDropWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Thumbnail Viewer Prototype")
        self.setAcceptDrops(True)
        self.resize(900, 600)

        self._thumbnailer = FileThumbnailer()

        layout = QtWidgets.QVBoxLayout(self)

        self._info_label = QtWidgets.QLabel("ファイルをドロップしてサムネイルを確認")
        self._info_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self._info_label)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QtWidgets.QWidget()
        self._grid = QtWidgets.QGridLayout(self._container)
        self._grid.setSpacing(8)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        self._size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._size_slider.setRange(64, 4096)
        self._size_slider.setValue(256)
        self._size_slider.setTickInterval(256)
        self._size_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._size_label = QtWidgets.QLabel("Size: 256")
        self._max_btn = QtWidgets.QPushButton("Max")
        self._max_btn.setFixedWidth(50)
        self._max_btn.clicked.connect(self._on_max_clicked)
        size_layout = QtWidgets.QHBoxLayout()
        size_layout.addWidget(QtWidgets.QLabel("64"))
        size_layout.addWidget(self._size_slider, 1)
        size_layout.addWidget(QtWidgets.QLabel("4096"))
        size_layout.addWidget(self._size_label)
        size_layout.addWidget(self._max_btn)
        layout.addLayout(size_layout)

        self._last_paths: list[str] = []
        self._size_slider.valueChanged.connect(self._on_size_changed)

    def _on_max_clicked(self):
        if not self._last_paths:
            return
        max_dim = 0
        for p in self._last_paths:
            dims = self._thumbnailer.get_file_dimensions(p)
            if dims:
                max_dim = max(max_dim, dims[0], dims[1])
        if max_dim > 0:
            self._size_slider.setValue(min(max_dim, 4096))
            self._show_thumbnails(self._last_paths, min(max_dim, 4096))

    def _on_size_changed(self, val):
        self._size_label.setText(f"Size: {val}")
        if self._last_paths:
            self._show_thumbnails(self._last_paths, val)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                p = url.toLocalFile()
                if os.path.exists(p):
                    paths.append(p)
        if paths:
            self._last_paths = paths
            self._show_thumbnails(paths, self._size_slider.value())

    def _show_thumbnails(self, paths: list[str], size: int):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        cols = max(1, (self.width() - 40) // (size + 20))
        total_thumb_ms = 0.0
        total_dims_ms = 0.0

        for i, path in enumerate(paths):
            row, col = divmod(i, cols)
            card = self._make_card(path, size)
            total_thumb_ms += card["thumb_ms"]
            total_dims_ms += card["dims_ms"]
            self._grid.addWidget(card["widget"], row, col, QtCore.Qt.AlignTop)

        self._info_label.setText(
            f"{len(paths)} files | "
            f"Thumbnail: {total_thumb_ms:.1f}ms total ({total_thumb_ms/max(len(paths),1):.1f}ms/file) | "
            f"Dimensions: {total_dims_ms:.1f}ms total ({total_dims_ms/max(len(paths),1):.1f}ms/file)"
        )

    def _make_card(self, path: str, size: int) -> dict:
        frame = QtWidgets.QFrame()
        frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        vbox = QtWidgets.QVBoxLayout(frame)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(2)

        t0 = time.perf_counter()
        try:
            img = self._thumbnailer.get_thumbnail(path, size=size)
        except Exception as e:
            img = None
        thumb_ms = (time.perf_counter() - t0) * 1000

        thumb_label = QtWidgets.QLabel()
        thumb_label.setAlignment(QtCore.Qt.AlignCenter)
        thumb_label.setMinimumSize(size, size)
        if img:
            pixmap = pil_to_qpixmap(img)
            thumb_label.setPixmap(pixmap)
            thumb_size_text = f"{img.width}x{img.height}"
        else:
            thumb_label.setText("N/A")
            thumb_size_text = "N/A"
        vbox.addWidget(thumb_label)

        t1 = time.perf_counter()
        dims = self._thumbnailer.get_file_dimensions(path)
        dims_ms = (time.perf_counter() - t1) * 1000

        name = os.path.basename(path)
        if len(name) > 30:
            name = name[:27] + "..."
        dims_text = f"{dims[0]}x{dims[1]}" if dims else "N/A"
        ratio_text = f"{dims[0]/dims[1]:.3f}" if dims else "N/A"

        info = QtWidgets.QLabel(
            f"{name}\n"
            f"Thumb: {thumb_size_text} ({thumb_ms:.1f}ms)\n"
            f"Real: {dims_text} ratio={ratio_text} ({dims_ms:.1f}ms)"
        )
        info.setWordWrap(True)
        info.setAlignment(QtCore.Qt.AlignCenter)
        font = info.font()
        font.setPointSize(8)
        info.setFont(font)
        vbox.addWidget(info)

        return {"widget": frame, "thumb_ms": thumb_ms, "dims_ms": dims_ms}


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    w = ThumbnailDropWidget()
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
