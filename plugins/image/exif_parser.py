from __future__ import annotations
import re
import os
import unicodedata
from typing import Any, Tuple, Dict

from PIL import Image, ExifTags
from PIL.TiffImagePlugin import IFDRational

from source.common.logs import AppLogger

TAGS = ExifTags.TAGS
GPSTAGS = ExifTags.GPSTAGS

_ORIENTATION_TAG = 274

XP_TAGS = {
    0x9C9B: "XPTitle",
    0x9C9C: "XPComment",
    0x9C9D: "XPAuthor",
    0x9C9E: "XPKeywords",
    0x9C9F: "XPSubject",
}

_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')


def _clean_text(s: Any) -> str:
    if not isinstance(s, str):
        s = str(s)
    s = s.replace('\x00', '')
    s = _CONTROL_CHARS_RE.sub('', s)
    s = unicodedata.normalize('NFC', s)
    return s


def _looks_binary_payload(b: bytes) -> Tuple[bool, float]:
    if not b:
        return (False, 0.0)
    ctrl = sum(1 for x in b if (x < 0x20 and x not in (0x09, 0x0A, 0x0D)) or x == 0x7F)
    high = sum(1 for x in b if x > 0x7E)
    n = len(b)
    both = high + ctrl
    return (both / n > 0.50, both / n)


def _summarize_binary_value(key: str, b: bytes, ratio: float) -> str:
    head = b[:6].hex()
    return f"<bin={key}; ratio={ratio*100:.1f}%; size={len(b)}; head={head}…>"


def _looks_utf16(bytez: bytes) -> bool:
    if not bytez:
        return False
    if bytez.startswith(b'\xff\xfe') or bytez.startswith(b'\xfe\xff'):
        return True
    window = bytez[:64]
    return window.count(b'\x00') / max(1, len(window)) > 0.25


def _decode_bytes_safely(b: bytes) -> str:
    try:
        return _clean_text(b.decode('utf-8'))
    except UnicodeDecodeError:
        pass
    if _looks_utf16(b):
        for enc in ('utf-16', 'utf-16-le', 'utf-16-be'):
            try:
                return _clean_text(b.decode(enc))
            except UnicodeDecodeError:
                continue
    try:
        return _clean_text(b.decode('utf-8', errors='ignore'))
    except Exception:
        return _clean_text(b.decode('latin-1', errors='ignore'))


def _decode_xp_value(v: Any) -> str:
    if isinstance(v, list):
        try:
            v = bytes(v)
        except (TypeError, ValueError):
            return _clean_text(v)
    if isinstance(v, (bytes, bytearray)):
        v = bytes(v)
        try:
            s = v.decode('utf-16-le')
        except Exception:
            s = v.decode('utf-16-le', errors='ignore')
        return _clean_text(s)
    return _clean_text(v)


def _decode_user_comment(b: bytes) -> str:
    if not isinstance(b, (bytes, bytearray)) or len(b) < 8:
        return _decode_bytes_safely(bytes(b) if isinstance(b, bytearray) else b)
    b = bytes(b)
    prefix, payload = b[:8], b[8:]
    try:
        if prefix == b'ASCII\x00\x00\x00':
            return _clean_text(payload.decode('ascii', errors='ignore'))
        if prefix == b'UNICODE\x00':
            try:
                s = payload.decode('utf-16')
            except UnicodeDecodeError:
                s = payload.decode('utf-16-le', errors='ignore')
            return _clean_text(s)
        if prefix == b'JIS\x00\x00\x00\x00':
            for enc in ('shift_jis', 'cp932', 'euc_jp'):
                try:
                    return _clean_text(payload.decode(enc))
                except UnicodeDecodeError:
                    continue
            return _clean_text(payload.decode('latin-1', errors='ignore'))
        return _decode_bytes_safely(payload)
    except Exception:
        return _decode_bytes_safely(payload)


def _rational_to_float(x: Any) -> float | None:
    try:
        if isinstance(x, IFDRational):
            return float(x)
        if isinstance(x, tuple) and len(x) == 2:
            num, den = x
            return float(num) / float(den) if den else None
        return float(x)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _dms_to_deg(dms: Any, ref: str | None) -> float | None:
    if not dms or not isinstance(dms, (tuple, list)) or len(dms) != 3:
        return None
    d = _rational_to_float(dms[0])
    m = _rational_to_float(dms[1])
    s = _rational_to_float(dms[2])
    if d is None or m is None or s is None:
        return None
    deg = d + m / 60.0 + s / 3600.0
    if ref and ref.upper() in ('S', 'W'):
        deg = -deg
    return deg


def _orientation_adjusted_size(w: int, h: int, orientation: int) -> Tuple[int, int]:
    if orientation in (5, 6, 7, 8):
        return h, w
    return w, h


class ExifParser:

    @staticmethod
    def _to_str(v: Any, *, tag_id: int | None = None, tag_name: str | None = None) -> str:
        if tag_id in XP_TAGS or (tag_name and tag_name in XP_TAGS.values()):
            return _decode_xp_value(v)
        if (tag_id == 0x9286) or (tag_name == 'UserComment'):
            if isinstance(v, (bytes, bytearray)):
                return _decode_user_comment(bytes(v))
            return _clean_text(v)
        if isinstance(v, (bytes, bytearray)):
            return _decode_bytes_safely(bytes(v))
        if isinstance(v, IFDRational):
            try:
                return _clean_text(str(float(v)))
            except (TypeError, ValueError):
                return _clean_text(f"{v.numerator}/{v.denominator}")
        if isinstance(v, tuple):
            try:
                return _clean_text(", ".join(ExifParser._to_str(x) for x in v))
            except (TypeError, ValueError, RecursionError):
                return _clean_text(repr(v))
        if isinstance(v, list):
            try:
                if v and isinstance(v[0], int) and 0 <= v[0] <= 255:
                    return _decode_bytes_safely(bytes(v))
            except (TypeError, ValueError, IndexError):
                return _clean_text(v)
            return _clean_text(v)
        return _clean_text(v)

    @classmethod
    def _parse_gps(cls, gps_ifd: dict) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        try:
            if not isinstance(gps_ifd, dict):
                return out
            g = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}

            for k2, v2 in g.items():
                out[f"GPS/{k2}"] = cls._to_str(v2)

            lat = lon = None
            if 'GPSLatitude' in g and 'GPSLatitudeRef' in g:
                lat = _dms_to_deg(g['GPSLatitude'], cls._to_str(g['GPSLatitudeRef']).upper())
            if 'GPSLongitude' in g and 'GPSLongitudeRef' in g:
                lon = _dms_to_deg(g['GPSLongitude'], cls._to_str(g['GPSLongitudeRef']).upper())

            if lat is not None:
                out["GPS/GPSLatitudeDecimal"] = lat
            if lon is not None:
                out["GPS/GPSLongitudeDecimal"] = lon
        except Exception as e:
            AppLogger.warning("parse gps failed", exc=e)
        return out

    @classmethod
    def _extract_from_exif_obj(cls, exif) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if not exif:
            return out
        for tag_id, val in exif.items():
            tag_name = TAGS.get(tag_id)
            if tag_name == 'GPSInfo' and isinstance(val, dict):
                out.update(cls._parse_gps(val))
                continue
            if tag_name:
                out[tag_name] = cls._to_str(val, tag_id=tag_id, tag_name=tag_name)
            else:
                key = f"Tag_{tag_id}"
                out[key] = cls._to_str(val, tag_id=tag_id, tag_name=key)
        return out

    @classmethod
    def extract_exif(cls, img: Image.Image) -> Dict[str, Any]:
        try:
            return cls._extract_from_exif_obj(img.getexif())
        except Exception as e:
            AppLogger.warning("extract_exif failed", exc=e)
            return {}

    @staticmethod
    def parse_info_dict(info: dict) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for k, v in (info or {}).items():
            key = str(k)
            if isinstance(v, (bytes, bytearray)):
                bb = bytes(v)
                is_bin, ratio = _looks_binary_payload(bb)
                if is_bin:
                    val_str = _summarize_binary_value(key, bb, ratio)
                else:
                    val_str = _decode_bytes_safely(bb)
            else:
                val_str = _clean_text(ExifParser._to_str(v))
            out[key] = val_str
        return out

    @classmethod
    def parse_file(cls, path: str) -> dict:
        result = {
            "filepath": path,
            "filename": os.path.basename(path),
            "width": None,
            "height": None,
            "aspect": None,
            "orientation": None,
            "exif": {},
            "info_items": {},
            "error": None,
        }
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                orientation = 1
                if exif:
                    raw = exif.get(_ORIENTATION_TAG)
                    if isinstance(raw, int):
                        orientation = raw
                w, h = _orientation_adjusted_size(*img.size, orientation)
                result["width"] = w
                result["height"] = h
                result["orientation"] = orientation
                result["aspect"] = (w / h) if h else 1.0
                result["exif"] = cls._extract_from_exif_obj(exif)
                result["info_items"] = cls.parse_info_dict(img.info or {})
        except Exception as e:
            result["error"] = f"{e}"
        return result

    @classmethod
    def parse_img(cls, img: Image.Image) -> dict:
        try:
            exif = img.getexif()
            orientation = 1
            if exif:
                raw = exif.get(_ORIENTATION_TAG)
                if isinstance(raw, int):
                    orientation = raw
            w, h = _orientation_adjusted_size(*img.size, orientation)
            return {
                "width": w,
                "height": h,
                "orientation": orientation,
                "aspect": (w / h) if h else 1.0,
                "exif": cls._extract_from_exif_obj(exif),
                "info_items": cls.parse_info_dict(img.info or {}),
                "error": None,
            }
        except Exception as e:
            return {
                "width": None,
                "height": None,
                "orientation": None,
                "aspect": 1.0,
                "exif": {},
                "info_items": {},
                "error": f"{e}",
            }
