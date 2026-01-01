from __future__ import annotations

def set_seed_specs(*, mouse_specs=None, key_specs=None) -> None:
    global _mouse_specs, _key_specs
    if mouse_specs is not None:
        _mouse_specs = mouse_specs
    if key_specs is not None:
        _key_specs = key_specs

def get_seed_mouse_specs():
    return _mouse_specs

def get_seed_key_specs():
    return _key_specs

_mouse_specs = None
_key_specs = None
