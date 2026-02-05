from __future__ import annotations

from typing import Any

from ..store_base import BindingStoreBase
from ..seed import get_seed_key_bindings
from .sequence import KeySequence


class KeyBindingStore(BindingStoreBase[KeySequence]):
    key_type = KeySequence
    def _seed_specs(self) -> Any | None:
        return get_seed_key_bindings()

