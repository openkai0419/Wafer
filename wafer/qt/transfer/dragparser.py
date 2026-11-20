import os
import platform
import re

from PySide6.QtCore import QBuffer, QIODevice, QMimeData
from PySide6.QtGui import QImage

from ...core.logs import AppLogger
from ...core.common.paths import normalize_path, safe_exists, safe_getsize
from ...core.platform.path_utils import is_http_url, sanitize_filename


_FILE_DESCRIPTOR_LAYOUTS = {
    True: (592, 520, "utf-16le"),
    False: (332, 260, "mbcs"),
}


def _file_group_descriptor_format(mime: QMimeData) -> str | None:
    formats = [f for f in mime.formats() if f.startswith("application/x-qt-windows-mime") and "FileGroupDescriptor" in f]
    return next((f for f in formats if "FileGroupDescriptorW" in f), formats[0] if formats else None)


def _encode_png(image: QImage) -> bytes | None:
    if image.isNull():
        return None
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        return None
    return bytes(buffer.data())


class ParsedItem:
    def __init__(self, source, name, is_binary=False, mime_type="", size=None):
        self.source = source
        self.name = name
        self.is_binary = is_binary
        self.mime_type = mime_type
        self.size = size

    def is_local_file(self):
        return not self.is_binary and isinstance(self.source, str) and safe_exists(self.source)


class MimeDataParser:
    def can_accept(self, mime: QMimeData, deny_formats=()):
        if mime is None:
            return False
        for fmt in deny_formats or ():
            if fmt and mime.hasFormat(str(fmt)):
                return False
        if platform.system() == "Windows" and _file_group_descriptor_format(mime):
            return True
        if mime.hasImage():
            return True
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    p = url.toLocalFile()
                    if p:
                        return True
                else:
                    s = url.toString()
                    if s and not s.startswith("blob:"):
                        return True
        if mime.hasText():
            t = (mime.text() or "").strip()
            return t.startswith("http://") or t.startswith("https://")
        return False

    def parse_content_disposition(self, header):
        if not header:
            return None
        m = re.search("filename\\*?=(?:UTF-8\\'\\')?[\"\\']?([^\"\\';]+)", header, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    def parse(self, mime):
        items = []
        has_local_url = False
        if mime is not None and mime.hasUrls():
            try:
                for url in mime.urls() or []:
                    if url is not None and url.isLocalFile() and url.toLocalFile():
                        has_local_url = True
                        break
            except (RuntimeError, AttributeError):
                has_local_url = False
        if platform.system() == "Windows" and not has_local_url:
            fmt = _file_group_descriptor_format(mime)
            if fmt:
                try:
                    items.extend(self._parse_windows_clipboard(mime, fmt))
                except ValueError as e:
                    AppLogger.warning("Invalid Windows virtual-file drop data", exc=e)
                if items:
                    return items
        if mime.hasImage():
            data = _encode_png(QImage(mime.imageData()))
            if data is not None:
                return [ParsedItem(source=data, name="image.png", is_binary=True, mime_type="image/png", size=len(data))]
            AppLogger.warning("Dropped image data could not be encoded as PNG")
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    src_path = normalize_path(url.toLocalFile())
                    if safe_exists(src_path):
                        fname = os.path.basename(src_path)
                        fsize = safe_getsize(src_path)
                        items.append(ParsedItem(source=src_path, name=fname, is_binary=False, size=fsize))
                else:
                    url_str = url.toString()
                    if url_str.startswith("blob:"):
                        continue
                    if is_http_url(url_str):
                        fname = url.fileName() or url.host() or "download"
                        fname = sanitize_filename(fname, fallback="download")
                        if not os.path.splitext(fname)[1]:
                            fname = fname + ".bin"
                        items.append(ParsedItem(source=url_str, name=fname, is_binary=False, mime_type="url"))
            if items:
                return items
        if mime.hasText():
            t = (mime.text() or "").strip()
            if is_http_url(t):
                items.append(ParsedItem(source=t, name="download.bin", is_binary=False, mime_type="url"))
                return items
        return items

    def _parse_windows_clipboard(self, mime, fmt):
        record_size, name_size, codec = _FILE_DESCRIPTOR_LAYOUTS["FileGroupDescriptorW" in fmt]
        data = bytes(mime.data(fmt))
        if len(data) < 4:
            raise ValueError("Invalid FileGroupDescriptor")
        count = int.from_bytes(data[0:4], "little")
        if len(data) < 4 + count * record_size:
            raise ValueError(f"Truncated FileGroupDescriptor: {count} entries in {len(data)} bytes")
        results = []
        for i in range(count):
            name_start = 4 + i * record_size + 72
            filename = data[name_start : name_start + name_size].decode(codec, errors="replace").split("\x00", 1)[0].strip()
            if not filename:
                raise ValueError(f"Failed to extract filename at index {i}")
            content_fmt = f'application/x-qt-windows-mime;value="FileContents";index={i}'
            if mime.hasFormat(content_fmt):
                content_data = mime.data(content_fmt)
            else:
                content_data = mime.data('application/x-qt-windows-mime;value="FileContents"')
            content_bytes = bytes(content_data)
            results.append(ParsedItem(source=content_bytes, name=filename, is_binary=True, size=len(content_bytes)))
        return results
