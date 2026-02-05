from __future__ import annotations

from typing import Any

from ..store_base import BindingStoreBase
from ..seed import get_seed_mouse_bindings
from .mouseeventmanager import MouseActionKey


class MouseBindingStore(BindingStoreBase[MouseActionKey]):
    key_type = MouseActionKey
    def _seed_specs(self) -> Any | None:
        return get_seed_mouse_bindings()
