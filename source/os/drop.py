import os
import platform
import re
import shutil
import requests
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QImage
from ..common.profiling import logger

def get_unique_filename(directory, name):
    base, ext = os.path.splitext(name)
    candidate = name
    counter = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f'{base} ({counter}){ext}'
        counter += 1
    return candidate

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

    def parse_content_disposition(self, header):
        if not header:
            return None
        m = re.search('filename\\*?=(?:UTF-8\\\'\\\')?["\\\']?([^"\\\';]+)', header, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    def parse(self, mime):
        items = []
        if platform.system() == 'Windows':
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
                    src_path = url.toLocalFile()
                    if os.path.exists(src_path):
                        fname = os.path.basename(src_path)
                        fsize = os.path.getsize(src_path)
                        items.append(ParsedItem(source=src_path, name=fname, is_binary=False, size=fsize))
                else:
                    url_str = url.toString()
                    if url_str.startswith('blob:'):
                        continue
                    try:
                        with requests.get(url_str, timeout=10, stream=True) as resp:
                            if resp.status_code == 200:
                                content = resp.content
                                ct = resp.headers.get('Content-Type', '')
                                cd = resp.headers.get('Content-Disposition', '')
                                fname = self.parse_content_disposition(cd)
                                if not fname:
                                    fname = url.fileName() or url.host() or 'download'
                                name, ext = os.path.splitext(fname)
                                if not ext and ct.startswith('image/'):
                                    ext = '.' + ct.split('/')[-1]
                                if not ext:
                                    ext = '.bin'
                                suggested = name + ext
                                size = len(content)
                                items.append(ParsedItem(source=content, name=suggested, is_binary=True, mime_type=ct, size=size))
                    except Exception as e:
                        logger.warning(f'Failed to download {url_str}: {e}')
                if items:
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
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if item.is_local_file():
            if move:
                shutil.move(item.source, target_path)
                logger.info(f'Moved: {item.source} → {target_path}')
            else:
                shutil.copy2(item.source, target_path)
                logger.info(f'Copied: {item.source} → {target_path}')
        elif item.is_binary and isinstance(item.source, (bytes, bytearray)):
            with open(target_path, 'wb') as f:
                f.write(item.source)
            logger.info(f'Saved binary data to {target_path}')
        else:
            raise ValueError('Invalid ParsedItem: inconsistent source and is_binary')
