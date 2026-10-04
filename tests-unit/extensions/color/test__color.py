from __future__ import annotations


import pytest

from extensions.color._color import hex_to_packed, normalize_tolerance, packed_to_hex, palette_tags, rgb_to_packed
from extensions.color.settings import palette_keys


def test_palette_tags_always_writes_all_palette_slots():
    keys = palette_keys(6)
    tags = palette_tags([rgb_to_packed(255, 0, 0), rgb_to_packed(0, 255, 0)], slots=6)
    assert tuple(tags.keys()) == keys
    assert tags["palette.1"] == "16711680"
    assert tags["palette.2"] == "65280"
    for key in keys[2:]:
        assert tags[key] == ""


def test_palette_tags_uses_requested_slot_count():
    tags = palette_tags([rgb_to_packed(255, 0, 0), rgb_to_packed(0, 255, 0), rgb_to_packed(0, 0, 255)], slots=2)
    assert tuple(tags.keys()) == ("palette.1", "palette.2")
    assert tags == {"palette.1": "16711680", "palette.2": "65280"}


def test_packed_hex_roundtrip():
    packed = hex_to_packed("#CC4422")
    assert packed == 0xCC4422
    assert packed_to_hex(packed) == "#CC4422"


def test_tolerance_is_clamped_ratio():
    assert normalize_tolerance(0.1) == pytest.approx(0.1)
    assert normalize_tolerance(1) == pytest.approx(1.0)
    assert normalize_tolerance(10) == pytest.approx(1.0)
    assert normalize_tolerance(-1) == pytest.approx(0.0)
