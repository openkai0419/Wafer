from dataclasses import dataclass
from PySide6.QtCore import QMimeData
import re
import os
import shutil
import platform
import requests

from ..profiling import logger, profiler

def get_unique_filename(directory: str, name: str) -> str:
    """If 'name' exists in 'directory', generate a new name to avoid overwriting."""
    base, ext = os.path.splitext(name)
    candidate = name
    counter = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base} ({counter}){ext}"
        counter += 1
    return candidate

@dataclass
class ParsedItem:
    """解析されたドロップデータ"""
    source: str | bytes        # ファイルパス or バイナリデータ
    name : str                 # 推奨ファイル名
    is_binary: bool = False    # Trueならbytes
    mime_type: str = ""

from PySide6.QtGui import QImage

class MimeDataParser:
    def parse_content_disposition(self, header: str) -> str | None:
        if not header:
            return None
        m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', header, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    def parse(self, mime: QMimeData) -> list[ParsedItem]:
        items = []

        # 3. Windows特殊形式（最初に見つけた1つだけ処理）
        if platform.system() == "Windows":
            fmt = next(
                (f for f in mime.formats()
                 if f.startswith("application/x-qt-windows-mime") and "FileGroupDescriptor" in f),
                None
            )
            if fmt:
                items.extend(self._parse_windows_clipboard(mime, fmt))
                if items:
                    return items

        # 1. 画像データ
        if mime.hasImage():
            qimage = QImage(mime.imageData())
            buffer = qimage.bits().asstring(qimage.sizeInBytes())

            formats = [f.lower() for f in mime.formats()]
            fmt = next(
                (f.split('/')[1] for f in formats if f.startswith("image/")),
                "png"
            )

            filename = f"image.{fmt}"
            items.append(ParsedItem(source=buffer, name=filename,
                                    is_binary=True, mime_type=f"image/{fmt}"))
            if items:
                return items

        # 2. URLリスト
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    src_path = url.toLocalFile()
                    if os.path.exists(src_path):
                        fname = os.path.basename(src_path)
                        items.append(ParsedItem(source=src_path, name=fname,
                                                is_binary=False))
                else:
                    url_str = url.toString()
                    if url_str.startswith("blob:"):
                        continue
                    try:
                        with requests.get(url_str, timeout=10, stream=True) as resp:
                            if resp.status_code == 200:
                                content = resp.content
                                ct = resp.headers.get("Content-Type", "")
                                cd = resp.headers.get("Content-Disposition", "")

                                fname = self.parse_content_disposition(cd)
                                if not fname:
                                    fname = url.fileName() or url.host() or "download"

                                name, ext = os.path.splitext(fname)
                                if not ext and ct.startswith("image/"):
                                    ext = "." + ct.split("/")[-1]
                                if not ext:
                                    ext = ".bin"

                                suggested = name + ext

                                items.append(ParsedItem(source=content, name=suggested,
                                                        is_binary=True, mime_type=ct))
                    except Exception as e:
                        logger.warning(f"Failed to download {url_str}: {e}")
                if items:
                    return items

        return items

    def _parse_windows_clipboard(self, mime: QMimeData, fmt: str) -> list[ParsedItem]:
        data = bytes(mime.data(fmt))
        if len(data) < 4:
            raise ValueError("Invalid FileGroupDescriptor")
        count = int.from_bytes(data[0:4], 'little')
        offset = 4
        results = []

        for i in range(count):
            # Windows FileGroupDescriptor パターン優先順位付き
            patterns = [
                (592, 72, 72+260, 'utf-16le'),  # Outlook
                (592, 72, 72+260, 'mbcs'),      # 古い形式
                (852, 332, 332+520, 'utf-16le') # 別バリエーション
            ]

            filename = None
            for size, start, end, codec in patterns:
                name_bytes = data[offset+start:offset+end]
                try:
                    decoded = name_bytes.decode(codec).split('\x00', 1)[0].strip()
                    if os.path.splitext(decoded)[1]:  # has extension
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
            results.append(ParsedItem(source=bytes(content_data), name=filename,
                                       is_binary=True))
        return results

class FileSaver:
    """ParsedItem を指定されたパスに保存する"""
    def save(self, item: ParsedItem, target_path: str):
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        if not item.is_binary and isinstance(item.source, str):
            # ローカルファイルコピー
            shutil.copy2(item.source, target_path)
            logger.info(f"Copied: {item.source} → {target_path}")
        elif item.is_binary and isinstance(item.source, (bytes, bytearray)):
            # バイト列を書き込む
            with open(target_path, 'wb') as f:
                f.write(item.source)
            logger.info(f"Saved binary data to {target_path}")
        else:
            raise ValueError("Invalid ParsedItem: inconsistent source and is_binary")
