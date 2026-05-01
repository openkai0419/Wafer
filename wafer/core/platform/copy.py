import os
import struct
import sys
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QGuiApplication


class ClipboardFileTransfer:
    def __init__(self):
        self.clipboard = QGuiApplication.clipboard()

    def set_files(self, file_paths, cut=False):
        if not file_paths:
            return
        unique_paths = list(dict.fromkeys(str(p) for p in file_paths if p))
        if len(unique_paths) != len(file_paths):
            from ...utils.logs import AppLogger

            AppLogger.warning(f"[clipboard] duplicate sources dropped: {len(file_paths)} -> {len(unique_paths)}")
        mime_data = QMimeData()
        urls = [QUrl.fromLocalFile(p) for p in unique_paths]
        mime_data.setUrls(urls)
        platform = sys.platform
        if platform.startswith("win"):
            self._set_windows_drop_effect(mime_data, cut)
        elif platform.startswith("linux"):
            self._set_linux_gnome_clipboard(mime_data, urls, cut)
        elif platform == "darwin":
            pass
        self.clipboard.setMimeData(mime_data)

    def _set_windows_drop_effect(self, mime_data, cut):
        effect = 2 if cut else 5
        data_bytes = struct.pack("<I", effect)
        mime_data.setData("Preferred DropEffect", data_bytes)

    def _set_linux_gnome_clipboard(self, mime_data, urls, cut):
        desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if any(env in desktop_env for env in ["gnome", "unity", "xfce", "cinnamon", "mate"]):
            op = "cut" if cut else "copy"
            uri_list = "".join(url.toString() + "\n" for url in urls)
            data = f"{op}\n{uri_list}".encode()
            mime_data.setData("x-special/gnome-copied-files", data)
