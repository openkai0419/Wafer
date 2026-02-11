from __future__ import annotations

from ..store_base import BindingStoreBase
from ..seed import get_key_preset_path
from .sequence import KeySequence


class KeyBindingStore(BindingStoreBase[KeySequence]):
    key_type = KeySequence

    def _seed_file_path(self) -> str | None:
        return get_key_preset_path()

