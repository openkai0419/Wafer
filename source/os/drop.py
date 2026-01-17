import os
import platform
import re
import shutil
import requests
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QImage
from ..common.profiling import logger
from ..common.funcs import normalize_path
from .file_transfer_utils import check_copy_conflict, sanitize_filename


def _is_http_url(s: str) -> bool:
    v = (s or '').strip().lower()
    return v.startswith('http://') or v.startswith('https://')

class ParsedItem:
    def __init__(self, source, name, is_binary=False, mime_type='', size=None):
        self.source = source
        self.name = name
        self.is_binary = is_binary
        self.mime_type = mime_type
        self.size = size

    def is_local_file(self):
        return not self.is_binary and isinstance(self.source, str) and os.path.exists(self.source)

class MimeDataParser:

    def can_accept(self, mime: QMimeData, deny_formats=()):
        if mime is None:
            return False
        for fmt in deny_formats or ():
            if fmt and mime.hasFormat(str(fmt)):
                return False
        if platform.system() == 'Windows':
            fmt = next((f for f in mime.formats() if f.startswith('application/x-qt-windows-mime') and 'FileGroupDescriptor' in f), None)
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
                    if s and not s.startswith('blob:'):
                        return True
        if mime.hasText():
            t = (mime.text() or '').strip()
            return t.startswith('http://') or t.startswith('https://')
        return False

    def parse_content_disposition(self, header):
        if not header:
            return None
        m = re.search('filename\\*?=(?:UTF-8\\\'\\\')?["\\\']?([^"\\\';]+)', header, re.IGNORECASE)
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
        if platform.system() == 'Windows' and not has_local_url:
            fmt = next((f for f in mime.formats() if f.startswith('application/x-qt-windows-mime') and 'FileGroupDescriptor' in f), None)
            if fmt:
                items.extend(self._parse_windows_clipboard(mime, fmt))
                if items:
                    return items
        if mime.hasImage():
            qimage = QImage(mime.imageData())
            buffer = qimage.bits().asstring(qimage.sizeInBytes())
            size = len(buffer)
            formats = [f.lower() for f in mime.formats()]
            fmt = next((f.split('/')[1] for f in formats if f.startswith('image/')), 'png')
            filename = f'image.{fmt}'
            items.append(ParsedItem(source=buffer, name=filename, is_binary=True, mime_type=f'image/{fmt}', size=size))
            if items:
                return items
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    src_path = normalize_path(url.toLocalFile())
                    if os.path.exists(src_path):
                        fname = os.path.basename(src_path)
                        fsize = os.path.getsize(src_path)
                        items.append(ParsedItem(source=src_path, name=fname, is_binary=False, size=fsize))
                else:
                    url_str = url.toString()
                    if url_str.startswith('blob:'):
                        continue
                    if _is_http_url(url_str):
                        fname = url.fileName() or url.host() or 'download'
                        fname = sanitize_filename(fname, fallback='download')
                        if not os.path.splitext(fname)[1]:
                            fname = fname + '.bin'
                        items.append(ParsedItem(source=url_str, name=fname, is_binary=False, mime_type='url'))
            if items:
                return items
        if mime.hasText():
            t = (mime.text() or '').strip()
            if _is_http_url(t):
                items.append(ParsedItem(source=t, name='download.bin', is_binary=False, mime_type='url'))
                return items
        return items

    def _parse_windows_clipboard(self, mime, fmt):
        data = bytes(mime.data(fmt))
        if len(data) < 4:
            raise ValueError('Invalid FileGroupDescriptor')
        count = int.from_bytes(data[0:4], 'little')
        offset = 4
        results = []
        for i in range(count):
            patterns = [(592, 72, 72 + 260, 'utf-16le'), (592, 72, 72 + 260, 'mbcs'), (852, 332, 332 + 520, 'utf-16le')]
            filename = None
            for size, start, end, codec in patterns:
                name_bytes = data[offset + start:offset + end]
                try:
                    decoded = name_bytes.decode(codec).split('\x00', 1)[0].strip()
                    if os.path.splitext(decoded)[1]:
                        filename = decoded
                        offset += size
                        break
                except Exception:
                    continue
            if not filename:
                raise ValueError(f'Failed to extract filename at index {i}')
            content_fmt = f'application/x-qt-windows-mime;value="FileContents";index={i}'
            if mime.hasFormat(content_fmt):
                content_data = mime.data(content_fmt)
            else:
                content_data = mime.data('application/x-qt-windows-mime;value="FileContents"')
            content_bytes = bytes(content_data)
            results.append(ParsedItem(source=content_bytes, name=filename, is_binary=True, size=len(content_bytes)))
        return results

class FileSaver:

    def save(self, item, target_path, move=False):
        d = os.path.dirname(target_path)
        if d:
            os.makedirs(d, exist_ok=True)
        if item.is_local_file():
            src = str(item.source)
            conflict = check_copy_conflict(src, target_path)
            if conflict:
                logger.warning(f'Skipped ({conflict}): {src} → {target_path}')
                return
            if os.path.isdir(src):
                if move:
                    shutil.move(src, target_path)
                    logger.info(f'Moved dir: {src} → {target_path}')
                else:
                    shutil.copytree(src, target_path)
                    logger.info(f'Copied dir: {src} → {target_path}')
                return
            if move:
                shutil.move(src, target_path)
                logger.info(f'Moved: {src} → {target_path}')
            else:
                shutil.copy2(src, target_path)
                logger.info(f'Copied: {src} → {target_path}')
            return
        if item.is_binary and isinstance(item.source, (bytes, bytearray)):
            with open(target_path, 'wb') as f:
                f.write(item.source)
            if move:
                logger.warning(f'Move requested for binary item; saved only: {target_path}')
            logger.info(f'Saved binary data to {target_path}')
            return
        if isinstance(item.source, str) and _is_http_url(item.source):
            url = item.source
            try:
                with requests.get(url, timeout=10, stream=True) as resp:
                    if resp.status_code != 200:
                        raise ValueError(f'HTTP {resp.status_code}')
                    with open(target_path, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                f.write(chunk)
                if move:
                    logger.warning(f'Move requested for URL item; downloaded only: {target_path}')
                logger.info(f'Downloaded: {url} → {target_path}')
                return
            except Exception as e:
                logger.warning(f'Failed to download {url}: {e}')
                return
        raise ValueError('Invalid ParsedItem: inconsistent source and is_binary')
