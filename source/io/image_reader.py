import os
import cv2
import re
import string
import unicodedata
import numpy as np
from PySide6 import QtCore, QtGui
from ..common.profiling import logger
from typing import Any
from PIL import Image, ExifTags
from PIL.TiffImagePlugin import IFDRational


class ImageReader:
    # --- const / tables ---
    ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

    TAGS = ExifTags.TAGS
    GPSTAGS = ExifTags.GPSTAGS
    XP_TAGS = {  # Windows XP UTF-16LE 系
        0x9C9B: "XPTitle",
        0x9C9C: "XPComment",
        0x9C9D: "XPAuthor",
        0x9C9E: "XPKeywords",
        0x9C9F: "XPSubject",
    }

    _CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')
    _PRINTABLE_SET = set(string.printable)

    def __init__(self, path: str):
        self.path = path

    # ---------- public ----------
    @classmethod
    def is_readable(cls, path: str) -> bool:
        return os.path.splitext(path)[-1].lower() in cls.ext

    def get_meta(self):
        p = self.path
        try:
            name = os.path.basename(p)
            with Image.open(p) as img:
                width, height = img.size

                # ★ クラスメソッドとして呼び出す
                exif_dict = self._extract_exif(img)

                # Orientation 補正
                exif = img.getexif()
                orientation = 1
                if exif:
                    try:
                        orientation = int(exif.get(274, 1))
                    except Exception:
                        orientation = 1
                if orientation in (5, 6, 7, 8):
                    width, height = height, width

                aspect = width / height if height else 1.0
                info = dict(img.info) if img.info else {}

            meta_info: list[tuple[str, str, str]] = []
            for k, v in info.items():
                meta_info.append((str(p), str(k), self._clean_text(self._to_str(v))))

            for k, v in exif_dict.items():
                meta_info.append((str(p), f"EXIF/{k}", self._clean_text(self._to_str(v))))

            meta_info.append((str(p), "__width__", self._clean_text(width)))
            meta_info.append((str(p), "__height__", self._clean_text(height)))
            meta_info.append((str(p), "__aspect__", self._clean_text(aspect)))
            meta_info.append((str(p), "__filepath__", self._clean_text(p)))

            return (p, p, name, aspect, meta_info, None)

        except Exception as e:
            logger.warning(f'Failed to process {p}: {e}')
            name = os.path.basename(p)
            return (p, p, name, None, [], 'fail')

    # ---------- helpers (text) ----------
    @classmethod
    def _clean_text(cls, s: Any) -> str:
        if not isinstance(s, str):
            s = str(s)
        s = s.replace('\x00', '')
        s = cls._CONTROL_CHARS_RE.sub('', s)
        return unicodedata.normalize('NFC', s)

    @staticmethod
    def _looks_utf16(bytez: bytes) -> bool:
        if not bytez:
            return False
        if bytez.startswith(b'\xff\xfe') or bytez.startswith(b'\xfe\xff'):
            return True
        window = bytez[:64]
        zero_ratio = window.count(b'\x00') / max(1, len(window))
        return zero_ratio > 0.25

    @classmethod
    def _decode_bytes_safely(cls, b: bytes) -> str:
        try:
            return cls._clean_text(b.decode('utf-8'))
        except Exception:
            pass
        if cls._looks_utf16(b):
            for enc in ('utf-16', 'utf-16-le', 'utf-16-be'):
                try:
                    return cls._clean_text(b.decode(enc, errors='strict'))
                except Exception:
                    continue
        try:
            return cls._clean_text(b.decode('utf-8', errors='ignore'))
        except Exception:
            return cls._clean_text(b.decode('latin-1', errors='ignore'))

    @classmethod
    def _score_text(cls, s: str) -> float:
        if not s:
            return -1e9
        bad = s.count('�')
        ctrl = sum(1 for ch in s if ord(ch) < 0x20 and ch not in '\t\n\r')
        vis_ascii = sum(1 for ch in s if ch in cls._PRINTABLE_SET and ch not in '\t\r')
        cjk_basic = sum(1 for ch in s if 0x3000 <= ord(ch) <= 0x30FF or 0x4E00 <= ord(ch) <= 0x9FFF)
        weird = sum(
            1 for ch in s
            if (0xE000 <= ord(ch) <= 0xF8FF)
            or (0xD800 <= ord(ch) <= 0xDFFF)
            or ord(ch) > 0x110000
        )
        length = len(s)
        score = (vis_ascii + 1.5 * cjk_basic) / length - 2.5 * (bad + ctrl + weird) / length
        blanks = sum(1 for ch in s if ch.isspace())
        if blanks / length > 0.8:
            score -= 1.0
        return score

    @classmethod
    def _try_codecs(cls, b: bytes) -> list[str]:
        candidates: list[bytes] = [b]
        if len(b) >= 2:
            candidates += [b[::2], b[1::2]]  # low/high 抜き出し
        outs: list[str] = []
        codecs = (
            'utf-8', 'utf-16', 'utf-16-le', 'utf-16-be',
            'utf-32', 'utf-32-le', 'utf-32-be'
        )
        for raw in candidates:
            for enc in codecs:
                try:
                    outs.append(raw.decode(enc))
                except Exception:
                    continue
            try:
                outs.append(raw.decode('utf-8', errors='ignore'))
            except Exception:
                pass
            outs.append(raw.decode('latin-1', errors='ignore'))
        # ユニーク
        seen, unique = set(), []
        for s in outs:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        return unique

    @classmethod
    def _smart_decode_exif_bytes(cls, b: bytes) -> str:
        if not isinstance(b, (bytes, bytearray)):
            return cls._clean_text(str(b))
        b = bytes(b)
        pool = [cls._decode_bytes_safely(b)] + cls._try_codecs(b)
        best = max(pool, key=cls._score_text)
        return cls._clean_text(best)

    @classmethod
    def _decode_xp_value(cls, v: Any) -> str:
        if isinstance(v, list):
            try:
                v = bytes(v)
            except Exception:
                return cls._clean_text(v)
        if isinstance(v, (bytes, bytearray)):
            return cls._smart_decode_exif_bytes(bytes(v))
        return cls._clean_text(v)

    @classmethod
    def _decode_user_comment(cls, b: bytes) -> str:
        if not isinstance(b, (bytes, bytearray)) or len(b) < 8:
            return cls._smart_decode_exif_bytes(bytes(b) if isinstance(b, bytearray) else b)
        b = bytes(b)
        prefix, payload = b[:8], b[8:]
        try:
            if prefix == b'ASCII\x00\x00\x00':
                return cls._clean_text(payload.decode('ascii', errors='ignore'))
            elif prefix == b'UNICODE\x00':
                try:
                    return cls._clean_text(payload.decode('utf-16', errors='strict'))
                except Exception:
                    return cls._clean_text(payload.decode('utf-16-le', errors='ignore'))
            elif prefix == b'JIS\x00\x00\x00\x00':
                for enc in ('shift_jis', 'cp932', 'euc_jp'):
                    try:
                        return cls._clean_text(payload.decode(enc))
                    except Exception:
                        continue
                return cls._clean_text(payload.decode('latin-1', errors='ignore'))
            else:
                return cls._smart_decode_exif_bytes(payload)
        except Exception:
            return cls._smart_decode_exif_bytes(payload)

    # ---------- helpers (values/GPS) ----------
    @staticmethod
    def _rational_to_float(x: Any) -> float | None:
        try:
            if isinstance(x, IFDRational):
                return float(x)
            if isinstance(x, tuple) and len(x) == 2:
                num, den = x
                return float(num) / float(den) if den else None
            return float(x)
        except Exception:
            return None

    @classmethod
    def _dms_to_deg(cls, dms: Any, ref: str | None) -> float | None:
        if not dms or not isinstance(dms, (tuple, list)) or len(dms) != 3:
            return None
        d = cls._rational_to_float(dms[0])
        m = cls._rational_to_float(dms[1])
        s = cls._rational_to_float(dms[2])
        if d is None or m is None or s is None:
            return None
        deg = d + m / 60.0 + s / 3600.0
        if ref and ref.upper() in ('S', 'W'):
            deg = -deg
        return deg

    @classmethod
    def _to_str(cls, v: Any, *, tag_id: int | None = None, tag_name: str | None = None) -> str:
        if tag_id in cls.XP_TAGS or (tag_name and tag_name in cls.XP_TAGS.values()):
            return cls._decode_xp_value(v)
        if (tag_id == 0x9286) or (tag_name == 'UserComment'):
            if isinstance(v, (bytes, bytearray)):
                return cls._decode_user_comment(bytes(v))
            return cls._clean_text(v)
        if isinstance(v, (bytes, bytearray)):
            return cls._smart_decode_exif_bytes(bytes(v))
        if isinstance(v, IFDRational):
            try:
                return cls._clean_text(str(float(v)))
            except Exception:
                return cls._clean_text(f"{v.numerator}/{v.denominator}")
        if isinstance(v, tuple):
            try:
                return cls._clean_text(", ".join(cls._to_str(x) for x in v))
            except Exception:
                return cls._clean_text(repr(v))
        if isinstance(v, list):
            try:
                if v and isinstance(v[0], int) and 0 <= v[0] <= 255:
                    return cls._smart_decode_exif_bytes(bytes(v))
            except Exception:
                pass
            return cls._clean_text(v)
        return cls._clean_text(v)

    @classmethod
    def _parse_gps(cls, gps_ifd: dict) -> dict[str, Any]:
        out: dict[str, Any] = {}
        try:
            if not isinstance(gps_ifd, dict):
                return out
            g = {cls.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
            for k2, v2 in g.items():
                out[f"GPS/{k2}"] = cls._to_str(v2)
            lat = lon = None
            if 'GPSLatitude' in g and 'GPSLatitudeRef' in g:
                lat = cls._dms_to_deg(
                    g['GPSLatitude'],
                    cls._to_str(g['GPSLatitudeRef']).upper()
                )
            if 'GPSLongitude' in g and 'GPSLongitudeRef' in g:
                lon = cls._dms_to_deg(
                    g['GPSLongitude'],
                    cls._to_str(g['GPSLongitudeRef']).upper()
                )
            if lat is not None:
                out["GPS/GPSLatitudeDecimal"] = lat
            if lon is not None:
                out["GPS/GPSLongitudeDecimal"] = lon
        except Exception:
            pass
        return out

    @classmethod
    def _extract_exif(cls, img: Image.Image) -> dict[str, Any]:
        out: dict[str, Any] = {}
        try:
            exif = img.getexif()
            if not exif:
                return out
            for tag_id, val in exif.items():
                tag_name = cls.TAGS.get(tag_id)
                if tag_name == 'GPSInfo' and isinstance(val, dict):
                    out.update(cls._parse_gps(val))
                    continue
                if tag_name:
                    out[f"{tag_name}"] = cls._to_str(val, tag_id=tag_id, tag_name=tag_name)
                else:
                    key = f"Tag_{tag_id}"
                    out[key] = cls._to_str(val, tag_id=tag_id, tag_name=key)
        except Exception:
            pass
        return out


        
class ImageLoader:
    ext = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

    def __init__(self, path):
        self.path = path
    
    @classmethod
    def is_loadable(cls, path):
        return os.path.splitext(path)[-1].lower() in cls.ext

    # --- 変更点1: Qt側での縮小をデコーダにやらせる ---
    def _qt_read(self, size: QtCore.QSize | None, keep_aspect: bool) -> QtGui.QPixmap | None:
        reader = QtGui.QImageReader(self.path)
        reader.setAutoTransform(True)
        if size is not None:
            # デコード時に縮小してメモリ使用/コピーを抑える
            if keep_aspect:
                # アスペクト維持は、長辺基準でscaledSizeを近似指定
                # Qtは微妙にズレることがあるがコスト対効果が高い
                sz = self._approx_aspect_keep_size(reader, size)
                reader.setScaledSize(sz)
            else:
                reader.setScaledSize(size)
        img = reader.read()
        if img.isNull():
            return None
        return QtGui.QPixmap.fromImage(img)

    def _approx_aspect_keep_size(self, reader: QtGui.QImageReader, target: QtCore.QSize) -> QtCore.QSize:
        # 原寸が読めない場合もあるため、ヘッダだけ先に読む
        sz = reader.size()
        if not sz.isValid():
            return target  # 情報が無ければそのまま
        tw, th = target.width(), target.height()
        rw, rh = sz.width(), sz.height()
        if rw <= 0 or rh <= 0 or tw <= 0 or th <= 0:
            return target
        # 長辺合わせ
        if rw >= rh:
            scale = tw / rw
        else:
            scale = th / rh
        sw, sh = max(1, int(rw * scale)), max(1, int(rh * scale))
        return QtCore.QSize(sw, sh)

    # --- 変更点2: JPEGはIMREAD_REDUCED_*で軽量デコード ---
    def _imread_flags_for_size(self, ext: str, size: QtCore.QSize | None):
        # 既定
        flags = cv2.IMREAD_UNCHANGED
        if size is None:
            return flags
        if ext in ('.jpg', '.jpeg'):
            # 長辺から粗い縮小率を選ぶ
            try:
                # ファイルヘッダから大きさを取れないので、いったん通常デコードしてしまうのは本末転倒。
                # そこで目安としてターゲットが小さければ強めに縮小。
                longest = max(size.width(), size.height())
                if longest <= 256:
                    flags = cv2.IMREAD_REDUCED_COLOR_8
                elif longest <= 512:
                    flags = cv2.IMREAD_REDUCED_COLOR_4
                elif longest <= 1024:
                    flags = cv2.IMREAD_REDUCED_COLOR_2
                else:
                    flags = cv2.IMREAD_COLOR  # ほぼ原寸
            except Exception:
                pass
        return flags

    # --- 変更点3: QImageコピー削減（numpyバッファを保持） ---
    def _numpy_to_qimage(self, img: np.ndarray) -> QtGui.QImage:
        # 16bit→8bit（内部統一）
        if img.dtype == np.uint16:
            img = (img >> 8).astype(np.uint8)

        if img.ndim == 2:
            buf = np.ascontiguousarray(img)
            q = QtGui.QImage(buf.data, buf.shape[1], buf.shape[0], buf.strides[0],
                             QtGui.QImage.Format_Grayscale8)
            q._buf = buf  # バッファ寿命をQImageと同調
            return q

        if img.ndim == 3:
            h, w, c = img.shape
            if c == 2:
                g, a = cv2.split(img)
                rgb = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
                rgba = np.ascontiguousarray(np.dstack([rgb, a]))
                q = QtGui.QImage(rgba.data, w, h, rgba.strides[0],
                                 QtGui.QImage.Format_RGBA8888)
                q._buf = rgba
                return q
            if c == 3:
                # BGR→RGB（ascontiguousでコピー1回のみ）
                rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                q = QtGui.QImage(rgb.data, w, h, rgb.strides[0],
                                 QtGui.QImage.Format_RGB888)
                q._buf = rgb
                return q
            if c == 4:
                rgba = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA))
                q = QtGui.QImage(rgba.data, w, h, rgba.strides[0],
                                 QtGui.QImage.Format_RGBA8888)
                q._buf = rgba
                return q

        raise ValueError('Unsupported image dimensions/channels')

    # --- 変更点4: 分類は据え置き（但しOpenCV優先度をやや上げる） ---
    def _classify_opencv_array(self, arr: np.ndarray, ext: str) -> str:
        if arr is None:
            return 'qt'
        if arr.ndim not in (2, 3):
            return 'qt'
        if arr.dtype in (np.float16, np.float32, np.float64):
            return 'qt'
        if arr.ndim == 3:
            c = arr.shape[2]
            if c not in (2, 3, 4):
                return 'qt'
            if ext in ('.jpg', '.jpeg') and c == 4:
                return 'qt'
            if ext == '.png' and (c == 2 or arr.dtype == np.uint16):
                return 'qt'
        if arr.dtype not in (np.uint8, np.uint16):
            return 'qt'
        return 'opencv'

    # --- 変更点5: 本体 ---
    def load(self, size: QtCore.QSize | None = None) -> QtGui.QPixmap | None:
        path = self.path
        ext = os.path.splitext(path)[-1].lower()
        try:
            # 1) GIFは既存仕様：Qt + 比率維持
            if ext == '.gif':
                return self._qt_read(size, keep_aspect=True)

            # 2) OpenCVで先に高速経路を試す
            flags = self._imread_flags_for_size(ext, size)
            try:
                data = np.fromfile(path, dtype=np.uint8)
            except Exception:
                # fromfileが遅い/失敗する環境向けフォールバック
                with open(path, 'rb') as f:
                    data = np.frombuffer(f.read(), dtype=np.uint8)
            arr = cv2.imdecode(data, flags)

            route = self._classify_opencv_array(arr, ext)
            if route != 'opencv':
                # Qt優先（既存仕様：GIF以外はサイズ指定時は比率無視）
                pix = self._qt_read(size, keep_aspect=False)
                if pix is not None:
                    return pix
                # Qt失敗 → OpenCV継続

            if arr is None:
                # どちらも失敗気味 → 最終的にQtで再挑戦
                return self._qt_read(size, keep_aspect=(ext == '.gif'))

            # 3) 必要な時だけリサイズ（既に近ければスキップ）
            if size is not None:
                h, w = arr.shape[:2]
                if (abs(w - size.width()) + abs(h - size.height())) > 2:
                    # 縮小ならAREA、拡大ならLANCZOS4
                    interp = cv2.INTER_AREA if (size.width() < w or size.height() < h) else cv2.INTER_LANCZOS4
                    arr = cv2.resize(arr, (size.width(), size.height()), interpolation=interp)

            # 4) NumPy -> QImage（コピー最小化）-> QPixmap
            qimg = self._numpy_to_qimage(arr)
            return QtGui.QPixmap.fromImage(qimg)

        except Exception as e:
            # 最終フォールバック: Qt
            try:
                pix = self._qt_read(size, keep_aspect=(ext == '.gif'))
                if pix is not None:
                    return pix
            except Exception:
                pass
            logger.warning(f'[ImageLoader] Failed to load image: {path} ({e})')
            return None
