import os
import platform
import re

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QImage

from ...utils.paths import normalize_path, safe_exists, safe_getsize
from .path_utils import is_http_url, sanitize_filename


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
        if platform.system() == "Windows":
            fmt = next((f for f in mime.formats() if f.startswith("application/x-qt-windows-mime") and "FileGroupDescriptor" in f), None)
            if fmt:
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
            except Exception:
                has_local_url = False
        if platform.system() == "Windows" and not has_local_url:
            fmt = next((f for f in mime.formats() if f.startswith("application/x-qt-windows-mime") and "FileGroupDescriptor" in f), None)
            if fmt:
                items.extend(self._parse_windows_clipboard(mime, fmt))
                if items:
                    return items
        if mime.hasImage():
            qimage = QImage(mime.imageData())
            buffer = qimage.bits().asstring(qimage.sizeInBytes())
            size = len(buffer)
            formats = [f.lower() for f in mime.formats()]
            fmt = next((f.split("/")[1] for f in formats if f.startswith("image/")), "png")
            filename = f"image.{fmt}"
            items.append(ParsedItem(source=buffer, name=filename, is_binary=True, mime_type=f"image/{fmt}", size=size))
            if items:
                return items
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
        data = bytes(mime.data(fmt))
        if len(data) < 4:
            raise ValueError("Invalid FileGroupDescriptor")
        count = int.from_bytes(data[0:4], "little")
        offset = 4
        results = []
        for i in range(count):
            patterns = [(592, 72, 72 + 260, "utf-16le"), (592, 72, 72 + 260, "mbcs"), (852, 332, 332 + 520, "utf-16le")]
            filename = None
            for size, start, end, codec in patterns:
                name_bytes = data[offset + start : offset + end]
                try:
                    decoded = name_bytes.decode(codec).split("\x00", 1)[0].strip()
                    if os.path.splitext(decoded)[1]:
                        filename = decoded
                        offset += size
                        break
                except Exception:
                    continue
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
