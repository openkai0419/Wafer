from typing import Any, Dict, List, Tuple, Union, Set, FrozenSet, Callable, Iterable, Optional
from weakref import WeakValueDictionary
from PySide6 import QtCore, QtGui, QtWidgets
from source.common.profiling import profiler
from ...command.core import CommandRegistry
from ...command.context import CommandContext
from ...utils import CommandPayload
from .sequence import KeySequence
from .runtime import KeyNameResolver, KeySpec
from .runtime import KeyPressState, RecentEventDeduper, ScanCodeMapper, KeyListenerRegistry
from .combo import ComboParser, ComboMatcher

KeyChordSpec = Union[Tuple[KeySpec, ...], List[KeySpec]]


class ShortcutManager(QtCore.QObject):
    _global: Optional['ShortcutManager'] = None
    _app_hooked_class: bool = False
    _scope_mode: str = "cursor"  # "focus" | "cursor"
    MAX_COMBO_LEN = 2
    MAX_RECENT_EVENTS = 128
    def __init__(self):
        super().__init__()
        self._keymap: Dict[int, Dict[FrozenSet[int], CommandPayload]] = {}
        self._states: Dict[int, KeyPressState] = {}
        self._key_listeners = KeyListenerRegistry()
        self._registry = CommandRegistry()
        self._app_hooked = False
        self._phys_listeners = KeyListenerRegistry()
        self._sc_mapper = ScanCodeMapper()
        self._sc_keymap: Dict[int, Dict[FrozenSet[int], CommandPayload]] = {}
        self._states_sc: Dict[int, KeyPressState] = {}
        self._deduper = RecentEventDeduper(self.MAX_RECENT_EVENTS)
        self._resolver = KeyNameResolver()
        self._parser = ComboParser(self._resolver)
        self._widget_refs: WeakValueDictionary[int, QtWidgets.QWidget] = WeakValueDictionary()
        if ShortcutManager._global is None:
            ShortcutManager._global = self
            self._is_global = True
        else:
            self._is_global = False
    @profiler.profile
    def set_bindings(self, widget: QtWidgets.QWidget, bindings: Dict[KeySequence, Any]):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.set_bindings(widget, bindings)
        self._ensure_app_filter()
        wid = id(widget)
        self._widget_refs[wid] = widget
        norm: Dict[FrozenSet[int], CommandPayload] = {}
        for seq, cmd in bindings.items():
            if not seq or not cmd:
                continue
            if not isinstance(cmd, CommandPayload):
                raise TypeError("Shortcut payload must be CommandPayload")
            if not isinstance(seq, KeySequence):
                raise TypeError("Key must be KeySequence")
            combo = self._parse_key_sequence(seq)
            if not combo:
                continue
            norm[combo] = cmd
        self._keymap[wid] = norm
        self._states[wid] = KeyPressState()
    def get_bindings(self, widget: QtWidgets.QWidget) -> Dict[str, CommandPayload]:
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.get_bindings(widget)
        wid = id(widget)
        r: Dict[str, CommandPayload] = {}
        for combo, payload in self._keymap.get(wid, {}).items():
            r[self._format_pretty(combo)] = payload
        return r
    def clear_bindings(self, widget: QtWidgets.QWidget):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.clear_bindings(widget)
        self.clear_key_bindings(widget)

    def set_key_bindings(self, widget: QtWidgets.QWidget, bindings: Dict[KeyChordSpec, Any]):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.set_key_bindings(widget, bindings)
        self._ensure_app_filter()
        wid = id(widget)
        self._widget_refs[wid] = widget
        norm: Dict[FrozenSet[int], CommandPayload] = {}
        for spec, cmd in bindings.items():
            if not cmd:
                continue
            if not isinstance(cmd, CommandPayload):
                raise TypeError("payload must be CommandPayload")
            combo = self._normalize(spec)
            if not combo or len(combo) > 2:
                continue
            norm[combo] = cmd
        self._keymap[wid] = norm
        self._states[wid] = KeyPressState()

    def get_key_bindings(self, widget: QtWidgets.QWidget) -> Dict[str, CommandPayload]:
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.get_key_bindings(widget)
        wid = id(widget)
        r: Dict[str, CommandPayload] = {}
        for combo, payload in self._keymap.get(wid, {}).items():
            r[self._format(combo)] = payload
        return r

    def clear_key_bindings(self, widget: QtWidgets.QWidget):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.clear_key_bindings(widget)
        wid = id(widget)
        self._keymap.pop(wid, None)
        self._states.pop(wid, None)
        self._widget_refs.pop(wid, None)

    def set_physical_bindings(self, widget: QtWidgets.QWidget, bindings: Dict[KeyChordSpec, Any]):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.set_physical_bindings(widget, bindings)
        self._ensure_app_filter()
        wid = id(widget)
        self._widget_refs[wid] = widget
        norm: Dict[FrozenSet[int], CommandPayload] = {}
        for spec, cmd in bindings.items():
            if not cmd:
                continue
            if not isinstance(cmd, CommandPayload):
                raise TypeError("payload must be CommandPayload")
            combo = self._normalize_sc(spec)
            if not combo or len(combo) > 2:
                continue
            norm[combo] = cmd
        self._sc_keymap[wid] = norm
        self._states_sc[wid] = KeyPressState()

    def get_physical_bindings(self, widget: QtWidgets.QWidget) -> Dict[str, CommandPayload]:
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.get_physical_bindings(widget)
        wid = id(widget)
        r: Dict[str, CommandPayload] = {}
        for combo, payload in self._sc_keymap.get(wid, {}).items():
            r[self._format_sc(combo)] = payload
        return r

    def clear_physical_bindings(self, widget: QtWidgets.QWidget):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.clear_physical_bindings(widget)
        wid = id(widget)
        self._sc_keymap.pop(wid, None)
        self._states_sc.pop(wid, None)
        if wid not in self._keymap and wid not in self._sc_keymap:
            self._widget_refs.pop(wid, None)

    def _get_scan_code(self, e: QtGui.QKeyEvent) -> int:
        try:
            return int(getattr(e, "nativeScanCode")())
        except Exception:
            return 0

    def _get_timestamp(self, e: QtGui.QKeyEvent) -> int:
        try:
            return int(getattr(e, "timestamp")())
        except Exception:
            return 0

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        et = event.type()
        if et in (QtCore.QEvent.ApplicationDeactivate, QtCore.QEvent.WindowDeactivate):
            self._reset_all_states()
            return False
        if not isinstance(obj, QtWidgets.QWidget):
            return False
        if ShortcutManager._scope_mode == "cursor":
            wid = self._resolve_target_widget_id_cursor()
        else:
            wid = self._resolve_target_widget_id_focus()
        if wid is None:
            return False
        et = event.type()
        if et == QtCore.QEvent.KeyPress:
            e: QtGui.QKeyEvent = event  # type: ignore
            if e.isAutoRepeat():
                return False
            k = int(e.key())
            if k == QtCore.Qt.Key_unknown:
                return False
            self._emit_phys(True, wid, e)
            ts = self._get_timestamp(e)
            sc = self._get_scan_code(e)
            stamp = (int(et), sc, k, ts, wid)
            if not self._deduper.add_and_check(stamp):
                return False
            self._key_listeners.emit_press(wid, k)
            if sc:
                state_sc = self._states_sc.setdefault(wid, KeyPressState())
                state_sc.add_pressed(sc)
                if wid in self._sc_keymap:
                    sc_combo = self._match_sc_combo(wid, require_len=2)
                    if sc_combo and not state_sc.is_fired(sc_combo):
                        state_sc.mark_fired(sc_combo)
                        self._exec(wid, self._sc_keymap[wid][sc_combo], e)
                        return True
            if sc:
                key_to_add = self._sc_mapper.map(wid, sc, k)
            else:
                key_to_add = k
            state = self._states.setdefault(wid, KeyPressState())
            state.add_pressed(int(key_to_add))
            if wid in self._keymap:
                combo = self._match_combo(wid, require_len=2)
                if combo and not state.is_fired(combo):
                    state.mark_fired(combo)
                    self._exec(wid, self._keymap[wid][combo], e)
                    return True
            return False
        if et == QtCore.QEvent.KeyRelease:
            e: QtGui.QKeyEvent = event  # type: ignore
            if e.isAutoRepeat():
                return False
            k = int(e.key())
            self._emit_phys(False, wid, e)
            ts = self._get_timestamp(e)
            sc = self._get_scan_code(e)
            stamp = (int(et), sc, k, ts, wid)
            if not self._deduper.add_and_check(stamp):
                return False
            if sc:
                state_sc = self._states_sc.setdefault(wid, KeyPressState())
                if wid in self._sc_keymap and not state_sc.is_consumed(sc):
                    single_sc = frozenset((sc,))
                    if single_sc in self._sc_keymap.get(wid, {}) and not state_sc.is_fired(single_sc):
                        state_sc.mark_fired(single_sc)
                        self._exec(wid, self._sc_keymap[wid][single_sc], e)
                state_sc.remove_pressed(sc)
                state_sc.cleanup_fired()
                state_sc.unconsume(sc)
            rk = k
            if sc:
                rk = self._sc_mapper.pop(wid, sc, rk)
            self._key_listeners.emit_release(wid, rk)
            state = self._states.setdefault(wid, KeyPressState())
            if wid in self._keymap and not state.is_consumed(rk):
                single = frozenset((rk,))
                if single in self._keymap.get(wid, {}) and not state.is_fired(single):
                    state.mark_fired(single)
                    self._exec(wid, self._keymap[wid][single], e)
            state.remove_pressed(rk)
            state.cleanup_fired()
            state.unconsume(rk)
            return False
        if et in (QtCore.QEvent.FocusOut, QtCore.QEvent.Hide, QtCore.QEvent.WindowDeactivate):
            self._reset_states_for(wid)
            return False
        return False

    def _exec(self, wid: int, payload: CommandPayload, event: Optional[QtGui.QKeyEvent] = None):
        widget = self._widget_refs.get(wid)
        kdisp = None
        if event is not None:
            try:
                kdisp = self._display_from_event(event)
            except Exception:
                kdisp = None
        if widget and hasattr(widget, "exec_command") and callable(widget.exec_command):
            widget.exec_command(payload, event=event, key=kdisp, source="key")
        else:
            args = dict(payload.args or {})
            try:
                scope = widget.binding_scope() if widget is not None and hasattr(widget, "binding_scope") and callable(widget.binding_scope) else ""
            except Exception:
                scope = ""
            ctx = CommandContext.create(widget, scope, source="key", event=event, key=kdisp)
            self._registry.execute(payload.id, ctx=ctx, **args)

    def _normalize(self, spec: KeyChordSpec) -> FrozenSet[int]:
        if not isinstance(spec, (tuple, list)):
            raise TypeError("key spec must be tuple or list")
        return self._parser.from_spec(spec)

    def _normalize_sc(self, spec: KeyChordSpec) -> FrozenSet[int]:
        if not isinstance(spec, (tuple, list)):
            raise TypeError("scan code spec must be tuple or list")
        return self._parser.from_sc_spec(spec)

    def _match_combo_generic(self, pressed: Set[int], combos: Dict[FrozenSet[int], CommandPayload], require_len: int = 0) -> FrozenSet[int] | None:
        return ComboMatcher.best_match(pressed, combos, require_len)

    def _match_combo(self, wid: int, require_len: int = 0) -> FrozenSet[int] | None:
        state = self._states.get(wid)
        if not state:
            return None
        return self._match_combo_generic(state.pressed, self._keymap.get(wid) or {}, require_len)

    def _match_sc_combo(self, wid: int, require_len: int = 0) -> FrozenSet[int] | None:
        state = self._states_sc.get(wid)
        if not state:
            return None
        return self._match_combo_generic(state.pressed, self._sc_keymap.get(wid) or {}, require_len)

    def _format(self, combo: FrozenSet[int]) -> str:
        return self._resolver.format_combo(combo, pretty=False)
    
    def _format_pretty(self, combo: FrozenSet[int]) -> str:
        return self._resolver.format_combo(combo, pretty=True)
    def _format_sc(self, combo: FrozenSet[int]) -> str:
        xs = sorted(list(combo))
        return "+".join(f"SC{int(x)}" for x in xs)

    def add_physical_key_listener(self, widget: QtWidgets.QWidget, on_press: Callable[[int, int, int, str, str], None] | None = None, on_release: Callable[[int, int, int, str, str], None] | None = None):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.add_physical_key_listener(widget, on_press, on_release)
        self._ensure_app_filter()
        wid = id(widget)
        if on_press:
            self._phys_listeners.add_press(wid, on_press)
        if on_release:
            self._phys_listeners.add_release(wid, on_release)
    def remove_physical_key_listeners(self, widget: QtWidgets.QWidget):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.remove_physical_key_listeners(widget)
        wid = id(widget)
        self._phys_listeners.remove_all(wid)
    def _emit_phys(self, is_press: bool, wid: int, e: QtGui.QKeyEvent):
        sc = self._get_scan_code(e)
        try:
            nv = int(getattr(e, "nativeVirtualKey")())
        except Exception:
            nv = 0
        k = int(e.key())
        txt = self.key_text_from_event(e, pretty=True)
        disp = self._display_from_event(e)
        if is_press:
            self._phys_listeners.emit_press(wid, sc, nv, k, txt, disp)
        else:
            self._phys_listeners.emit_release(wid, sc, nv, k, txt, disp)
    def _display_from_event(self, e: QtGui.QKeyEvent) -> str:
        mods = e.modifiers()
        mod_keys: List[int] = []
        if mods & QtCore.Qt.ControlModifier:
            mod_keys.append(int(QtCore.Qt.Key_Control))
        if mods & QtCore.Qt.ShiftModifier:
            mod_keys.append(int(QtCore.Qt.Key_Shift))
        if mods & QtCore.Qt.AltModifier:
            mod_keys.append(int(QtCore.Qt.Key_Alt))
        if mods & QtCore.Qt.MetaModifier:
            mod_keys.append(int(QtCore.Qt.Key_Meta))
        keys = mod_keys + [int(e.key())]
        return self._resolver.format_keys(keys, "+", True)
    
    def key_name(self, key: int, pretty: bool = True) -> str:
        return self._resolver.key_name(key, pretty)
    
    def format_keys(self, keys: Iterable[int], sep: str = "+", pretty: bool = True) -> str:
        return self._resolver.format_keys(keys, sep, pretty)
    
    def key_text_from_event(self, e: QtGui.QKeyEvent, pretty: bool = True) -> str:
        return self._resolver.key_text_from_event(e, pretty)
    def _parse_key_sequence(self, seq: KeySequence) -> FrozenSet[int]:
        return self._parser.from_sequence(seq)
    
    def _parse_string_combo(self, s: str) -> FrozenSet[int]:
        return self._parser.from_string(s)

    def add_key_listener(self, widget: QtWidgets.QWidget, on_press: Callable[[int], None] | None = None, on_release: Callable[[int], None] | None = None):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.add_key_listener(widget, on_press, on_release)
        self._ensure_app_filter()
        wid = id(widget)
        if on_press:
            self._key_listeners.add_press(wid, on_press)
        if on_release:
            self._key_listeners.add_release(wid, on_release)

    def remove_key_listeners(self, widget: QtWidgets.QWidget):
        if not self._is_global and ShortcutManager._global is not None:
            return ShortcutManager._global.remove_key_listeners(widget)
        wid = id(widget)
        self._key_listeners.remove_all(wid)
    def _ensure_app_filter(self):
        if ShortcutManager._app_hooked_class:
            return
        app = QtWidgets.QApplication.instance()
        if app and ShortcutManager._global is not None:
            try:
                for f in list(getattr(app, "eventFilters")() or []):
                    if isinstance(f, ShortcutManager):
                        try:
                            app.removeEventFilter(f)
                        except Exception:
                            pass
            except Exception:
                pass
            app.installEventFilter(ShortcutManager._global)
            ShortcutManager._app_hooked_class = True
    
    def _resolve_target_widget_id_focus(self) -> int | None:
        targets = set(self._keymap.keys()) | self._key_listeners.ids() | self._phys_listeners.ids()
        if not targets:
            return None
        w = QtWidgets.QApplication.focusWidget()
        if not w:
            return None
        wid = id(w)
        if wid in targets:
            return wid
        return None

    def _resolve_target_widget_id_cursor(self) -> int | None:
        targets = set(self._keymap.keys()) | self._key_listeners.ids() | self._phys_listeners.ids()
        if not targets:
            return None
        try:
            from ..manager import BindingManager
            gpt = QtGui.QCursor.pos()
            w = BindingManager.instance().find_binding_widget_at(gpt)
            if not w:
                return None
            wid = id(w)
            if wid in targets:
                return wid
            return None
        except Exception:
            return None

    @classmethod
    def set_scope_mode(cls, mode: str):
        m = str(mode).strip().lower()
        if m in ("focus", "cursor"):
            cls._scope_mode = m

    @classmethod
    def scope_mode(cls) -> str:
        return cls._scope_mode

    def _reset_states_for(self, wid: int):
        state = self._states.get(wid)
        if state:
            state.reset()
        state_sc = self._states_sc.get(wid)
        if state_sc:
            state_sc.reset()

    def _reset_all_states(self):
        wids = set(self._keymap.keys()) | set(self._states.keys()) | set(self._sc_keymap.keys()) | set(self._states_sc.keys())
        for wid in list(wids):
            self._reset_states_for(wid)
