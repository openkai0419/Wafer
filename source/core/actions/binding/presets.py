from __future__ import annotations

from pathlib import Path
from typing import List

from source.utils.paths import get_resource_path

_mouse_preset: str = "standard"
_key_preset: str = "standard"


def set_presets(*, mouse: str | None = None, key: str | None = None) -> None:
    global _mouse_preset, _key_preset
    if mouse is not None:
        _mouse_preset = mouse
    if key is not None:
        _key_preset = key


def get_mouse_preset() -> str:
    return _mouse_preset


def get_key_preset() -> str:
    return _key_preset


def get_mouse_preset_path() -> str:
    return str(get_resource_path() / "mouse_bindings" / f"{_mouse_preset}.json")


def get_key_preset_path() -> str:
    return str(get_resource_path() / "key_bindings" / f"{_key_preset}.json")


def list_presets(kind: str) -> List[str]:
    folder = get_resource_path() / f"{kind}_bindings"
    if not folder.is_dir():
        return []
    return sorted(f.stem for f in folder.glob("*.json"))
