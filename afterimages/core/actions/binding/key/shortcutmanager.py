from typing import Any, Dict, List, Tuple, Union, Set, Callable, Iterable, Optional, cast
from weakref import WeakValueDictionary
from PySide6 import QtCore, QtGui, QtWidgets
from afterimages.utils.profiling import profiler
from afterimages.utils.logs import AppLogger
from ...command.core import CommandRegistry
from ...command.context import CommandContext
from ...command.payload import CommandPayload
from afterimages.utils.helpers import invoke_int, widget_prop_bool
from .sequence import KeySequence
from .runtime import KeyNameResolver, KeySpec
from .runtime import KeyListenerRegistry
from .combo import ComboParser
from .chord_state import KeyChordStateManager, KeyEventStamp

KeyChordSpec = Union[Tuple[KeySpec, ...], List[KeySpec]]
KeyCombo = Tuple[int, ...]


def _delegate_to_global(fn):
    name = fn.__name__
    def wrapper(self, *args, **kwargs):
        if not self._is_global and ShortcutManager._global is not None:
            return getattr(ShortcutManager._global, name)(*args, **kwargs)
        return fn(self, *args, **kwargs)
    wrapper.__name__ = name
    return wrapper


class ShortcutManager(QtCore.QObject):
    _global: Optional['ShortcutManager'] = None
    _app_hooked_class: bool = False
    _scope_mode: str = "cursor"
    BLOCK_PARENT_SHORTCUTS_PROP: str = "block_parent_shortcuts"
    MAX_COMBO_LEN = 2
    MAX_RECENT_EVENTS = 128
    def __init__(self):
        super().__init__()
        self._keymap: Dict[int, Dict[KeyCombo, CommandPayload]] = {}
        self._key_listeners = KeyListenerRegistry()
        self._consume_key_listener_ids: Set[int] = set()
        self._registry = CommandRegistry()
        self._app_hooked = False
        self._phys_listeners = KeyListenerRegistry()
        self._sc_keymap: Dict[int, Dict[KeyCombo, CommandPayload]] = {}
        self._state = KeyChordStateManager(max_recent_events=self.MAX_RECENT_EVENTS)
        self._resolver = KeyNameResolver()
        self._parser = ComboParser(self._resolver)
        self._widget_refs: WeakValueDictionary[int, QtWidgets.QWidget] = WeakValueDictionary()
        self._targets_cache: Optional[Set[int]] = None
        if ShortcutManager._global is None:
            ShortcutManager._global = self
            self._is_global = True
        else:
            self._is_global = False

    @_delegate_to_global
    @profiler.profile
    def set_bindings(self, widget: QtWidgets.QWidget, bindings: Dict[KeySequence, Any]):
        self._ensure_app_filter()
        wid = id(widget)
        self._widget_refs[wid] = widget
        norm: Dict[KeyCombo, CommandPayload] = {}
        for seq, cmd in bindings.items():
            if not seq or not cmd:
                continue
            if not isinstance(seq, KeySequence):
                raise TypeError("Key must be KeySequence")
            try:
                payload = CommandPayload.from_any(cmd)
            except Exception as e:
                raise TypeError("Shortcut payload must be CommandPayload") from e
            combo = self._parse_key_sequence(seq)
            if not combo:
                continue
            norm[combo] = payload
        self._keymap[wid] = norm
        self._invalidate_targets_cache()
    @_delegate_to_global
    def get_bindings(self, widget: QtWidgets.QWidget) -> Dict[str, CommandPayload]:
        wid = id(widget)
        r: Dict[str, CommandPayload] = {}
        for combo, payload in self._keymap.get(wid, {}).items():
            r[self._format_pretty(combo)] = payload
        return r
    @_delegate_to_global
    def clear_bindings(self, widget: QtWidgets.QWidget):
        self.clear_key_bindings(widget)

    @_delegate_to_global
    def set_key_bindings(self, widget: QtWidgets.QWidget, bindings: Dict[KeyChordSpec, Any]):
        self._ensure_app_filter()
        wid = id(widget)
        self._widget_refs[wid] = widget
        norm: Dict[KeyCombo, CommandPayload] = {}
        for spec, cmd in bindings.items():
            if not cmd:
                continue
            try:
                payload = CommandPayload.from_any(cmd)
            except Exception as e:
                raise TypeError("payload must be CommandPayload") from e
            combo = self._normalize(spec)
            if not combo or len(combo) > 2:
                continue
            norm[combo] = payload
        self._keymap[wid] = norm
        self._invalidate_targets_cache()

    @_delegate_to_global
    def get_key_bindings(self, widget: QtWidgets.QWidget) -> Dict[str, CommandPayload]:
        wid = id(widget)
        r: Dict[str, CommandPayload] = {}
        for combo, payload in self._keymap.get(wid, {}).items():
            r[self._format(combo)] = payload
        return r

    @_delegate_to_global
    def clear_key_bindings(self, widget: QtWidgets.QWidget):
        wid = id(widget)
        self._keymap.pop(wid, None)
        self._widget_refs.pop(wid, None)
        self._invalidate_targets_cache()

    @_delegate_to_global
    def set_physical_bindings(self, widget: QtWidgets.QWidget, bindings: Dict[KeyChordSpec, Any]):
        self._ensure_app_filter()
        wid = id(widget)
        self._widget_refs[wid] = widget
        norm: Dict[KeyCombo, CommandPayload] = {}
        for spec, cmd in bindings.items():
            if not cmd:
                continue
            try:
                payload = CommandPayload.from_any(cmd)
            except Exception as e:
                raise TypeError("payload must be CommandPayload") from e
            combo = self._normalize_sc(spec)
            if not combo or len(combo) > 2:
                continue
            norm[combo] = payload
        self._sc_keymap[wid] = norm
        self._invalidate_targets_cache()

    @_delegate_to_global
    def get_physical_bindings(self, widget: QtWidgets.QWidget) -> Dict[str, CommandPayload]:
        wid = id(widget)
        r: Dict[str, CommandPayload] = {}
        for combo, payload in self._sc_keymap.get(wid, {}).items():
            r[self._format_sc(combo)] = payload
        return r

    @_delegate_to_global
    def clear_physical_bindings(self, widget: QtWidgets.QWidget):
        wid = id(widget)
        self._sc_keymap.pop(wid, None)
        if wid not in self._keymap and wid not in self._sc_keymap:
            self._widget_refs.pop(wid, None)
        self._invalidate_targets_cache()

    def _get_scan_code(self, e: QtGui.QKeyEvent) -> int:
        return invoke_int(e, "nativeScanCode", 0)

    def _get_timestamp(self, e: QtGui.QKeyEvent) -> int:
        return invoke_int(e, "timestamp", 0)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if not isinstance(event, QtCore.QEvent):
            return False
        et = event.type()
        if et in (QtCore.QEvent.ApplicationDeactivate, QtCore.QEvent.WindowDeactivate):
            self._reset_all_states()
            return False
        if et not in (
            QtCore.QEvent.KeyPress,
            QtCore.QEvent.KeyRelease,
            QtCore.QEvent.FocusOut,
            QtCore.QEvent.Hide,
            QtCore.QEvent.WindowDeactivate,
        ):
            return False
        if not isinstance(obj, QtWidgets.QWidget):
            return False
        if ShortcutManager._scope_mode == "cursor":
            wid = self._resolve_target_widget_id_cursor()
        else:
            wid = self._resolve_target_widget_id_focus()
        if wid is None:
            return False
        if et == QtCore.QEvent.KeyPress:
            e = cast(QtGui.QKeyEvent, event)
            if e.isAutoRepeat():
                return False
            k = int(e.key())
            if k == QtCore.Qt.Key_unknown:
                return False
            self._emit_phys(True, wid, e)
            ts = self._get_timestamp(e)
            sc = self._get_scan_code(e)
            if not self._state.dedupe(KeyEventStamp(int(et), int(sc), int(k), int(ts), int(wid))):
                return False
            self._key_listeners.emit_press(wid, k)
            if wid in self._consume_key_listener_ids:
                return True
            payload = self._state.payload_for_press(
                sc=int(sc),
                key=int(k),
                event=e,
                logical_map=self._keymap.get(wid),
                physical_map=self._sc_keymap.get(wid),
                require_len=2,
            )
            if payload is not None:
                self._exec(wid, payload, e)
                return True
            return False
        if et == QtCore.QEvent.KeyRelease:
            e = cast(QtGui.QKeyEvent, event)
            if e.isAutoRepeat():
                return False
            k = int(e.key())
            if k == QtCore.Qt.Key_unknown:
                return False
            self._emit_phys(False, wid, e)
            ts = self._get_timestamp(e)
            sc = self._get_scan_code(e)
            if not self._state.dedupe(KeyEventStamp(int(et), int(sc), int(k), int(ts), int(wid))):
                return False
            if sc:
                payload_sc = self._state.payload_for_physical_release(sc=int(sc), physical_map=self._sc_keymap.get(wid))
                if payload_sc is not None:
                    self._exec(wid, payload_sc, e)
            rk = k
            if sc:
                rk = self._state.pop_mapped_key(sc, rk)
            self._key_listeners.emit_release(wid, rk)
            if wid in self._consume_key_listener_ids:
                return True
            payload = self._state.payload_for_logical_release(key=int(rk), logical_map=self._keymap.get(wid))
            if payload is not None:
                self._exec(wid, payload, e)
            return False
        if et in (QtCore.QEvent.FocusOut, QtCore.QEvent.Hide, QtCore.QEvent.WindowDeactivate):
            self._reset_states_for(wid)
            return False
        return False

    def _exec(self, wid: int, payload: CommandPayload, event: Optional[QtGui.QKeyEvent] = None):
        widget = self._widget_refs.get(wid)
        kdisp = None
        if event is not None:
            kdisp = self._display_from_event(event)
        if widget and hasattr(widget, "exec_command") and callable(widget.exec_command):
            widget.exec_command(payload, event=event, key=kdisp, source="key")
        else:
            args = dict(payload.args or {})
            scope = ""
            if widget is not None and hasattr(widget, "binding_scope") and callable(widget.binding_scope):
                try:
                    scope = widget.binding_scope() or ""
                except Exception as e:
                    AppLogger.warning("binding_scope failed", exc=e)
            ctx = CommandContext.create(widget, scope, source="key", event=event)
            self._registry.execute(payload.id, ctx=ctx, **args)

    def _normalize(self, spec: KeyChordSpec) -> KeyCombo:
        if not isinstance(spec, (tuple, list)):
            raise TypeError("key spec must be tuple or list")
        return self._parser.from_spec(spec)

    def _normalize_sc(self, spec: KeyChordSpec) -> KeyCombo:
        if not isinstance(spec, (tuple, list)):
            raise TypeError("scan code spec must be tuple or list")
        return self._parser.from_sc_spec(spec)

    def _format(self, combo: KeyCombo) -> str:
        return self._resolver.format_combo(combo, pretty=False)
    
    def _format_pretty(self, combo: KeyCombo) -> str:
        return self._resolver.format_combo(combo, pretty=True)
    def _format_sc(self, combo: KeyCombo) -> str:
        return "+".join(f"SC{int(x)}" for x in combo)

    @_delegate_to_global
    def add_physical_key_listener(self, widget: QtWidgets.QWidget, on_press: Callable[[int, int, int, str, str], None] | None = None, on_release: Callable[[int, int, int, str, str], None] | None = None):
        self._ensure_app_filter()
        wid = id(widget)
        if on_press:
            self._phys_listeners.add_press(wid, on_press)
        if on_release:
            self._phys_listeners.add_release(wid, on_release)
        self._invalidate_targets_cache()
    @_delegate_to_global
    def remove_physical_key_listeners(self, widget: QtWidgets.QWidget):
        wid = id(widget)
        self._phys_listeners.remove_all(wid)
        self._invalidate_targets_cache()
    def _emit_phys(self, is_press: bool, wid: int, e: QtGui.QKeyEvent):
        sc = self._get_scan_code(e)
        nv = invoke_int(e, "nativeVirtualKey", 0)
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
    def _parse_key_sequence(self, seq: KeySequence) -> KeyCombo:
        return self._parser.from_sequence(seq)
    
    def _parse_string_combo(self, s: str) -> KeyCombo:
        return self._parser.from_string(s)

    @_delegate_to_global
    def add_key_listener(self, widget: QtWidgets.QWidget, on_press: Callable[[int], None] | None = None, on_release: Callable[[int], None] | None = None, consume: bool = False):
        self._ensure_app_filter()
        wid = id(widget)
        if consume:
            self._consume_key_listener_ids.add(wid)
        if on_press:
            self._key_listeners.add_press(wid, on_press)
        if on_release:
            self._key_listeners.add_release(wid, on_release)
        self._invalidate_targets_cache()

    @_delegate_to_global
    def remove_key_listeners(self, widget: QtWidgets.QWidget):
        wid = id(widget)
        self._key_listeners.remove_all(wid)
        self._consume_key_listener_ids.discard(wid)
        self._invalidate_targets_cache()
    def _ensure_app_filter(self):
        if ShortcutManager._app_hooked_class:
            return
        app = QtWidgets.QApplication.instance()
        if app and ShortcutManager._global is not None:
            app.installEventFilter(ShortcutManager._global)
            ShortcutManager._app_hooked_class = True

    def _invalidate_targets_cache(self):
        self._targets_cache = None

    def _get_targets(self) -> Set[int]:
        if self._targets_cache is None:
            self._targets_cache = set(self._keymap.keys()) | self._key_listeners.ids() | self._phys_listeners.ids()
        return self._targets_cache

    def _resolve_target_widget_id_from(self, start: QtWidgets.QWidget | None, targets: Set[int]) -> int | None:
        w = start
        while w is not None:
            wid = id(w)
            if wid in targets:
                return wid
            if widget_prop_bool(w, self.BLOCK_PARENT_SHORTCUTS_PROP):
                return None
            w = w.parentWidget()
        return None
    
    def _resolve_target_widget_id_focus(self) -> int | None:
        targets = self._get_targets()
        if not targets:
            return None
        w = QtWidgets.QApplication.focusWidget()
        return self._resolve_target_widget_id_from(w, targets)

    def _resolve_target_widget_id_cursor(self) -> int | None:
        targets = self._get_targets()
        if not targets:
            return None
        mw = QtWidgets.QApplication.activeModalWidget()
        if mw is not None:
            w = QtWidgets.QApplication.focusWidget() or mw
            wid = self._resolve_target_widget_id_from(w, targets)
            if wid is not None:
                return wid
        if QtWidgets.QApplication.instance() is None:
            return None
        gpt = QtGui.QCursor.pos()
        w = QtWidgets.QApplication.widgetAt(gpt)
        return self._resolve_target_widget_id_from(w, targets)

    @classmethod
    def set_scope_mode(cls, mode: str):
        m = str(mode).strip().lower()
        if m in ("focus", "cursor"):
            cls._scope_mode = m

    @classmethod
    def scope_mode(cls) -> str:
        return cls._scope_mode

    def _reset_states_for(self, wid: int):
        self._state.reset()

    def _reset_all_states(self):
        self._state.reset()
