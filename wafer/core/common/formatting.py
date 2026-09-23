import datetime
import math
import re

from ..logs import AppLogger

_NUM_SPLIT = re.compile(r"([0-9]+)").split

SOURCE_KEYS = ("source", "size", "created", "modified", "collected", "file_hash")
FILE_KEYS = ("name", "path", "aspect_ratio", "source_extension")
_SOURCE_TIME_KEYS = ("created", "modified", "collected")


def natural_key(s):
    return [int(c) if c.isascii() and c.isdigit() else c.casefold() for c in _NUM_SPLIT(s)]


def split_last(lst):
    return (lst[:-1], lst[-1]) if lst else ([], None)


def format_timestamp(ts: float) -> str:
    if ts is None:
        return None
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


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


def format_source_entries(record: dict) -> list[tuple[str, str]]:
    entries = []
    for key in SOURCE_KEYS:
        value = record.get(key)
        if value is None or value == "":
            continue
        try:
            if key == "size":
                value = format_size_detail(int(value))
            elif key in _SOURCE_TIME_KEYS:
                value = format_timestamp(float(value))
        except (TypeError, ValueError, OSError, OverflowError):
            AppLogger.warning(f"Unexpected {key} value in source record: {value!r}")
        entries.append((key, str(value)))
    return entries


def format_file_entries(record: dict) -> list[tuple[str, str]]:
    entries = []
    for key in FILE_KEYS:
        value = record.get(key)
        if value is None or value == "":
            continue
        if key == "aspect_ratio":
            try:
                value = format_aspect(float(value))
            except (TypeError, ValueError, OverflowError):
                AppLogger.warning(f"Unexpected aspect_ratio value: {value!r}")
        entries.append((key, str(value)))
    return entries


def display_prefixed_key(key: str) -> str:
    dot = key.find(".")
    if dot > 0:
        return f"[{key[:dot]}]  {key[dot + 1 :]}"
    return key
