import sys
import os
import struct
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QGuiApplication


class ClipboardFileTransfer:
    def __init__(self):
        self.clipboard = QGuiApplication.clipboard()

    def set_files(self, file_paths: list[str], cut: bool = False):
        """
        ファイルをクリップボードに設定して、エクスプローラーなどで Ctrl+V や「貼り付け」が可能にする。
        :param file_paths: ファイルパスのリスト（絶対パス）
        :param cut: Trueなら「切り取り」、Falseなら「コピー」
        """
        if not file_paths:
            return

        mime_data = QMimeData()
        urls = [QUrl.fromLocalFile(path) for path in file_paths]
        mime_data.setUrls(urls)

        platform = sys.platform

        if platform.startswith("win"):
            self._set_windows_drop_effect(mime_data, cut)

        elif platform.startswith("linux"):
            self._set_linux_gnome_clipboard(mime_data, urls, cut)

        elif platform == "darwin":
            # macOS: QUrlだけで十分（Finderではコピーのみ対応）
            pass  # 追加処理不要

        self.clipboard.setMimeData(mime_data)

    def _set_windows_drop_effect(self, mime_data: QMimeData, cut: bool):
        # Windowsでは Preferred DropEffect を指定（5: コピー, 2: 切り取り）
        effect = 2 if cut else 5
        data_bytes = struct.pack("<I", effect)  # Little endian 4バイト整数
        mime_data.setData("Preferred DropEffect", data_bytes)

    def _set_linux_gnome_clipboard(self, mime_data: QMimeData, urls: list[QUrl], cut: bool):
        # Linux (GNOME系) では x-special/gnome-copied-files を設定
        desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if any(env in desktop_env for env in ["gnome", "unity", "xfce", "cinnamon", "mate"]):
            op = "cut" if cut else "copy"
            uri_list = "".join(url.toString() + "\n" for url in urls)
            data = f"{op}\n{uri_list}".encode("utf-8")
            mime_data.setData("x-special/gnome-copied-files", data)
