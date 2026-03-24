import datetime
import math
import re
from PySide6 import QtGui


_NUM_SPLIT = re.compile(r'([0-9]+)').split


def natural_key(s):
    return [int(c) if c.isascii() and c.isdigit() else c.casefold() for c in _NUM_SPLIT(s)]


_cached_dpi: float | None = None


def dpix(px, base_dpi=96):
    global _cached_dpi
    if _cached_dpi is None:
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return px
        _cached_dpi = screen.logicalDotsPerInch()
    return int(px * _cached_dpi / base_dpi)

def split_last(lst):
    return (lst[:-1], lst[-1]) if lst else ([], None)

def is_dark_theme():
    palette = QtGui.QGuiApplication.palette()
    bg_color = palette.color(QtGui.QPalette.Window)
    return bg_color.value() < 128

def format_timestamp(ts: float) -> str:
    if ts is None:
        return None
    dt = datetime.datetime.fromtimestamp(ts)
    return  dt.strftime("%Y-%m-%d %H:%M:%S")

def format_aspect(ratio: float, max_denominator: int = 100) -> str:
    if ratio is None:
        return None
    if ratio <= 0:
        return "N/A"
    for den in range(1, max_denominator + 1):
        num = round(ratio * den)
        if abs(num / den - ratio) < 1e-6:
            g = math.gcd(num, den)
            return f"{num // g}:{den // g}"
    return f"{ratio:.2f}:1"

def format_size(size: int) -> str:
    if size is None:
        return None
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    s = float(size)
    for unit in units:
        if s < 1024:
            return f"{s:.1f} {unit}"
        s /= 1024
    return f"{s:.1f} EB"

def format_size_detail(size: int) -> str:
    if size is None:
        return None
    return f"{format_size(size)} ({size:,} bytes)"

def display_prefixed_key(key: str) -> str:
    dot = key.find('.')
    if dot > 0:
        return f'[{key[:dot]}]  {key[dot + 1:]}'
    return key
