from __future__ import annotations

import math

PALETTE_SLOTS = 6
PALETTE_KEYS = tuple(f"palette.{i}" for i in range(1, PALETTE_SLOTS + 1))


def rgb_to_packed(r: int, g: int, b: int) -> int:
    return (max(0, min(255, int(r))) << 16) | (max(0, min(255, int(g))) << 8) | max(0, min(255, int(b)))


def packed_to_rgb(value) -> tuple[int, int, int] | None:
    try:
        n = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    if n < 0 or n > 0xFFFFFF:
        return None
    return (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF


def packed_to_hex(value) -> str:
    rgb = packed_to_rgb(value)
    if rgb is None:
        return ""
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    text = str(value or "").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        return None
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return None


def hex_to_packed(value: str) -> int | None:
    rgb = hex_to_rgb(value)
    if rgb is None:
        return None
    return rgb_to_packed(*rgb)


def normalize_hex(value: str) -> str:
    rgb = hex_to_rgb(value)
    if rgb is None:
        return ""
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def normalize_tolerance(value: int | float) -> float:
    try:
        tolerance = float(value)
    except (TypeError, ValueError):
        tolerance = 0.1
    if tolerance > 1.0:
        tolerance /= 100.0
    return max(0.0, min(1.0, tolerance))


def tolerance_to_radius(tolerance: int | float) -> int:
    return round(math.sqrt(3 * 255 * 255) * normalize_tolerance(tolerance))


def palette_tags(packed_values: list[int]) -> dict[str, str]:
    values = list(packed_values[:PALETTE_SLOTS])
    tags: dict[str, str] = {}
    for i, key in enumerate(PALETTE_KEYS):
        tags[key] = str(int(values[i])) if i < len(values) else ""
    return tags


def color_param(value: dict) -> dict | None:
    if not isinstance(value, dict) or not value.get("enabled", True):
        return None
    rgb = hex_to_rgb(str(value.get("hex") or ""))
    if rgb is None:
        return None
    tolerance = normalize_tolerance(value.get("tolerance", 0.1))
    radius = tolerance_to_radius(tolerance)
    return {"hex": f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}", "rgb": rgb, "tolerance": tolerance, "radius_sq": radius * radius}
