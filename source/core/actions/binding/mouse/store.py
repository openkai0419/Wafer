from __future__ import annotations

from ..store_base import BindingStoreBase
from ..presets import get_mouse_preset_path
from .mouseeventmanager import MouseActionKey


class MouseBindingStore(BindingStoreBase[MouseActionKey]):
    key_type = MouseActionKey

    def _seed_file_path(self) -> str | None:
        return get_mouse_preset_path()
