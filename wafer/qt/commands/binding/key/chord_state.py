from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtGui

from ...command.payload import CommandPayload
from .runtime import KeyPressState, RecentEventDeduper, ScanCodeMapper
from .combo import KeyCombo, modifier_keys_from_qt


@dataclass(frozen=True)
class KeyEventStamp:
    event_type: int
    scan_code: int
    key: int
    timestamp: int
    widget_id: int


class KeyChordStateManager:
    def __init__(self, *, max_recent_events: int = 128):
        self._logical = KeyPressState()
        self._physical = KeyPressState()
        self._deduper = RecentEventDeduper(max_recent_events)
        self._sc_mapper = ScanCodeMapper()

    def reset(self):
        self._logical.reset()
        self._physical.reset()
        self._deduper.clear()
        self._sc_mapper.clear(0)

    def dedupe(self, stamp: KeyEventStamp) -> bool:
        return self._deduper.add_and_check((stamp.event_type, stamp.scan_code, stamp.key, stamp.timestamp, stamp.widget_id))

    def modifiers_from_event(self, e: QtGui.QKeyEvent) -> set[int]:
        return set(modifier_keys_from_qt(e.modifiers()))

    def pressed_for_match(self, *, include_modifiers: set[int] | None = None) -> set[int]:
        s = set(self._logical.pressed)
        if include_modifiers:
            s.update(include_modifiers)
        return s

    def physical_pressed_for_match(self) -> set[int]:
        return set(self._physical.pressed)

    def payload_for_press(
        self,
        *,
        sc: int,
        key: int,
        event: QtGui.QKeyEvent,
        logical_map: dict[KeyCombo, CommandPayload] | None,
        physical_map: dict[KeyCombo, CommandPayload] | None,
        require_len: int = 2,
    ) -> CommandPayload | None:
        if sc:
            self.add_physical_press(sc)
            if physical_map:
                combo_sc = self._combo_from_order(self._physical.order, require_len=require_len)
                if combo_sc and combo_sc in physical_map and not self.is_physical_fired(combo_sc):
                    self.mark_physical_fired(combo_sc)
                    return physical_map[combo_sc]
        eff = self.map_sc_to_key(sc, key) if sc else int(key)
        self.add_logical_press(eff)
        if logical_map:
            combo = self._combo_from_event(event=event, key=int(eff), require_len=require_len)
            if combo and combo in logical_map and not self.is_logical_fired(combo):
                self.mark_logical_fired(combo)
                return logical_map[combo]
        return None

    def payload_for_physical_release(self, *, sc: int, physical_map: dict[KeyCombo, CommandPayload] | None) -> CommandPayload | None:
        payload = None
        was_down = bool(sc) and int(sc) in self._physical.pressed
        if sc and physical_map and was_down:
            payload = self.physical_single_fire(sc=sc, combo_map=physical_map)
        if sc:
            self.remove_physical_press(sc)
        return payload

    def payload_for_logical_release(self, *, key: int, logical_map: dict[KeyCombo, CommandPayload] | None) -> CommandPayload | None:
        payload = None
        was_down = int(key) in self._logical.pressed
        if logical_map and was_down:
            payload = self.logical_single_fire(key=key, combo_map=logical_map)
        self.remove_logical_press(key)
        return payload

    def add_physical_press(self, sc: int):
        self._physical.add_pressed(int(sc))

    def remove_physical_press(self, sc: int):
        self._physical.remove_pressed(int(sc))
        self._physical.cleanup_fired()
        self._physical.clear_consumed(int(sc))

    def add_logical_press(self, key: int):
        self._logical.add_pressed(int(key))

    def remove_logical_press(self, key: int):
        self._logical.remove_pressed(int(key))
        self._logical.cleanup_fired()
        self._logical.clear_consumed(int(key))

    def is_logical_consumed(self, key: int) -> bool:
        return self._logical.is_consumed(int(key))

    def is_physical_consumed(self, sc: int) -> bool:
        return self._physical.is_consumed(int(sc))

    def is_logical_fired(self, combo: KeyCombo) -> bool:
        return self._logical.is_fired(combo)

    def is_physical_fired(self, combo: KeyCombo) -> bool:
        return self._physical.is_fired(combo)

    def mark_logical_fired(self, combo: KeyCombo):
        self._logical.mark_fired(combo)

    def mark_physical_fired(self, combo: KeyCombo):
        self._physical.mark_fired(combo)

    def map_sc_to_key(self, sc: int, key: int) -> int:
        return int(self._sc_mapper.record(0, int(sc), int(key)))

    def pop_mapped_key(self, sc: int, default: int) -> int:
        return int(self._sc_mapper.pop(0, int(sc), int(default)))

    def has_any_pressed(self) -> bool:
        return bool(self._logical.pressed or self._physical.pressed)

    def consume_only(self, key: int | None = None, sc: int | None = None):
        if key is not None:
            self._logical.consumed[int(key)] = True
        if sc is not None:
            self._physical.consumed[int(sc)] = True

    def physical_single_fire(self, *, sc: int, combo_map: dict[KeyCombo, CommandPayload]) -> CommandPayload | None:
        if self.is_physical_consumed(sc):
            return None
        single = (int(sc),)
        if single in combo_map and not self.is_physical_fired(single):
            self.mark_physical_fired(single)
            return combo_map[single]
        return None

    def logical_single_fire(self, *, key: int, combo_map: dict[KeyCombo, CommandPayload]) -> CommandPayload | None:
        if self.is_logical_consumed(key):
            return None
        single = (int(key),)
        if single in combo_map and not self.is_logical_fired(single):
            self.mark_logical_fired(single)
            return combo_map[single]
        return None

    def _combo_from_order(self, order: list[int], *, require_len: int) -> KeyCombo | None:
        if require_len <= 0:
            return None
        if len(order) < require_len:
            return None
        return tuple(int(x) for x in order[-require_len:])

    def _primary_modifier(self, mods: set[int]) -> int | None:
        if int(QtCore.Qt.Key_Control) in mods:
            return int(QtCore.Qt.Key_Control)
        if int(QtCore.Qt.Key_Shift) in mods:
            return int(QtCore.Qt.Key_Shift)
        if int(QtCore.Qt.Key_Alt) in mods:
            return int(QtCore.Qt.Key_Alt)
        if int(QtCore.Qt.Key_Meta) in mods:
            return int(QtCore.Qt.Key_Meta)
        return None

    def _combo_from_event(self, *, event: QtGui.QKeyEvent, key: int, require_len: int) -> KeyCombo | None:
        if require_len == 2:
            mods = self.modifiers_from_event(event)
            pm = self._primary_modifier(mods)
            if pm is not None and int(key) not in (int(QtCore.Qt.Key_Control), int(QtCore.Qt.Key_Shift), int(QtCore.Qt.Key_Alt), int(QtCore.Qt.Key_Meta)):
                return (int(pm), int(key))
            return self._combo_from_order(self._logical.order, require_len=2)
        if require_len == 1:
            return (int(key),)
        return None
