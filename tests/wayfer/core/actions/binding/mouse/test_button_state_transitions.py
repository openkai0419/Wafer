import pytest
from unittest.mock import patch
from PySide6 import QtCore, QtGui, QtWidgets

from wayfer.core.actions.binding.mixins import CommandBindingMixin
from wayfer.core.actions.binding.mouse.types import (
    ClickType,
    MouseActionKey,
    MouseButton,
)
from wayfer.core.actions.binding.mouse.manager import (
    MouseEventManager,
    MouseEventDispatcher,
    MouseStateManager,
)
from wayfer.core.actions.command.payload import CommandPayload


class _TestWidget(QtWidgets.QWidget, CommandBindingMixin):
    pass


LMB = QtCore.Qt.MouseButton.LeftButton
RMB = QtCore.Qt.MouseButton.RightButton
MMB = QtCore.Qt.MouseButton.MiddleButton
NO_BTN = QtCore.Qt.MouseButton.NoButton
NO_MOD = QtCore.Qt.KeyboardModifier.NoModifier
CTRL = QtCore.Qt.KeyboardModifier.ControlModifier
SHIFT = QtCore.Qt.KeyboardModifier.ShiftModifier


def _make_event(evt_type, button, buttons_held, mods=NO_MOD, pos=(50, 50)):
    return QtGui.QMouseEvent(
        evt_type,
        QtCore.QPointF(*pos),
        QtCore.QPointF(*pos),
        QtCore.QPointF(*pos),
        button,
        button | buttons_held,
        mods,
    )


def _press(button, buttons_held=NO_BTN, mods=NO_MOD, pos=(50, 50)):
    return _make_event(QtCore.QEvent.Type.MouseButtonPress, button, buttons_held, mods, pos)


def _release(button, buttons_held=NO_BTN, mods=NO_MOD, pos=(50, 50)):
    return _make_event(QtCore.QEvent.Type.MouseButtonRelease, button, buttons_held, mods, pos)


class ActionRecorder:
    def __init__(self):
        self.calls = []

    def make_handler(self, label):
        def handler(event=None):
            self.calls.append(label)
            return True
        return handler

    @property
    def labels(self):
        return list(self.calls)

    def clear(self):
        self.calls.clear()


@pytest.fixture
def qtbot():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class _Bot:
        def __init__(self):
            self._widgets = []

        def addWidget(self, w):
            self._widgets.append(w)
            w.show()
            QtWidgets.QApplication.processEvents()

    bot = _Bot()
    yield bot
    for w in reversed(bot._widgets):
        w.close()
    QtWidgets.QApplication.processEvents()


@pytest.fixture(autouse=True)
def _reset_state():
    MouseStateManager._instance = None
    yield
    MouseStateManager._instance = None


def _setup_widget(qtbot, bindings_map=None):
    w = _TestWidget()
    qtbot.addWidget(w)
    w.init_command_binding("TestScope", use_existing_events=True)

    recorder = ActionRecorder()
    mgr = w._mouse_manager

    if bindings_map:
        for key, label in bindings_map.items():
            mgr.bind(key, recorder.make_handler(label))
            if key.click_type in (ClickType.WHEEL_UP, ClickType.WHEEL_DOWN):
                w._mouse_bindings[key] = CommandPayload("__test__." + label)

    return w, recorder


def _inject(dispatcher, widget, event):
    dispatcher._state._processed_events.clear()
    dispatcher.eventFilter(widget, event)


def _inject_press(disp, w, button, buttons_held=NO_BTN, mods=NO_MOD):
    _inject(disp, w, _press(button, buttons_held, mods))


def _inject_release(disp, w, button, buttons_held=NO_BTN, mods=NO_MOD):
    _inject(disp, w, _release(button, buttons_held, mods))


# ---------------------------------------------------------------------------
# 1. 単一ボタン Press→Release: SINGLE発火
# ---------------------------------------------------------------------------

class TestSingleButtonPressRelease:

    def test_left_click(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE): "L_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, LMB)
            assert rec.labels == []
            _inject_release(d, w, LMB)
            assert rec.labels == ["L_SINGLE"]

    def test_right_click(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_release(d, w, RMB)
            assert rec.labels == ["R_SINGLE"]

    def test_middle_click(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.MIDDLE, ClickType.SINGLE): "M_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, MMB)
            _inject_release(d, w, MMB)
            assert rec.labels == ["M_SINGLE"]


# ---------------------------------------------------------------------------
# 2. held_buttonsなし + 修飾キー
# ---------------------------------------------------------------------------

class TestModifiers:

    def test_ctrl_left_click(self, qtbot):
        from wayfer.core.actions.binding.mouse.types import ModifierKey
        key = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, modifiers=(ModifierKey.CTRL,))
        w, rec = _setup_widget(qtbot, {key: "CTRL_L"})
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, LMB, mods=CTRL)
            _inject_release(d, w, LMB, mods=CTRL)
            assert rec.labels == ["CTRL_L"]


# ---------------------------------------------------------------------------
# 3. 2ボタン同時: Right hold + Left click → LEFT+held(RIGHT) 発火
# ---------------------------------------------------------------------------

class TestTwoButtonCombinations:

    def test_right_hold_left_click(self, qtbot):
        key = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, held_buttons=(MouseButton.RIGHT,))
        w, rec = _setup_widget(qtbot, {
            key: "L_HELD_R",
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_press(d, w, LMB, buttons_held=RMB)
            _inject_release(d, w, LMB, buttons_held=RMB)
            assert "L_HELD_R" in rec.labels

    def test_right_hold_left_click_suppresses_right_single(self, qtbot):
        key = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, held_buttons=(MouseButton.RIGHT,))
        w, rec = _setup_widget(qtbot, {
            key: "L_HELD_R",
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_press(d, w, LMB, buttons_held=RMB)
            _inject_release(d, w, LMB, buttons_held=RMB)
            rec.clear()
            _inject_release(d, w, RMB)
            assert "R_SINGLE" not in rec.labels

    def test_left_hold_right_click(self, qtbot):
        key = MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, held_buttons=(MouseButton.LEFT,))
        w, rec = _setup_widget(qtbot, {
            key: "R_HELD_L",
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE): "L_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, LMB)
            _inject_press(d, w, RMB, buttons_held=LMB)
            _inject_release(d, w, RMB, buttons_held=LMB)
            assert "R_HELD_L" in rec.labels

    def test_left_hold_right_click_suppresses_left_single(self, qtbot):
        key = MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, held_buttons=(MouseButton.LEFT,))
        w, rec = _setup_widget(qtbot, {
            key: "R_HELD_L",
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE): "L_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, LMB)
            _inject_press(d, w, RMB, buttons_held=LMB)
            _inject_release(d, w, RMB, buttons_held=LMB)
            rec.clear()
            _inject_release(d, w, LMB)
            assert "L_SINGLE" not in rec.labels


# ---------------------------------------------------------------------------
# 4. ボタン解放順序の入れ替え: A press → B press → A release → B release
# ---------------------------------------------------------------------------

class TestReleaseOrderVariations:

    def test_right_press_left_press_right_release_left_release(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, held_buttons=(MouseButton.RIGHT,)): "L_HELD_R",
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE): "L_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_press(d, w, LMB, buttons_held=RMB)
            _inject_release(d, w, RMB, buttons_held=LMB)
            _inject_release(d, w, LMB)
        assert "L_HELD_R" not in rec.labels or "R_SINGLE" not in rec.labels or "L_SINGLE" not in rec.labels

    def test_left_press_right_press_left_release_right_release(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, held_buttons=(MouseButton.LEFT,)): "R_HELD_L",
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE): "L_SINGLE",
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, LMB)
            _inject_press(d, w, RMB, buttons_held=LMB)
            _inject_release(d, w, LMB, buttons_held=RMB)
            _inject_release(d, w, RMB)
        assert "R_HELD_L" not in rec.labels or "L_SINGLE" not in rec.labels or "R_SINGLE" not in rec.labels


# ---------------------------------------------------------------------------
# 5. バインドなしのボタン組み合わせ: 状態が破壊されないこと
# ---------------------------------------------------------------------------

class TestUnboundCombinations:

    def test_unbound_buttons_dont_corrupt_state(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE): "L_SINGLE",
        })
        d = w._mouse_dispatcher
        state = d._state
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_release(d, w, RMB)

            _inject_press(d, w, LMB)
            _inject_release(d, w, LMB)
            assert rec.labels == ["L_SINGLE"]

    def test_unbound_held_combo_no_side_effect(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE): "L_SINGLE",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_press(d, w, LMB, buttons_held=RMB)
            _inject_release(d, w, LMB, buttons_held=RMB)
            _inject_release(d, w, RMB)

            rec.clear()
            _inject_press(d, w, LMB)
            _inject_release(d, w, LMB)
            assert rec.labels == ["L_SINGLE"]


# ---------------------------------------------------------------------------
# 6. ダブルクリック
# ---------------------------------------------------------------------------

class TestDoubleClick:

    def test_double_click_fires_double_action(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE): "L_SINGLE",
            MouseActionKey(MouseButton.LEFT, ClickType.DOUBLE): "L_DOUBLE",
        })
        d = w._mouse_dispatcher
        state = d._state
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, LMB)
            _inject_release(d, w, LMB)
            assert rec.labels == ["L_SINGLE"]

            state.set_double_click_button(w, LMB)
            _inject_press(d, w, LMB)
            _inject_release(d, w, LMB)
            assert "L_DOUBLE" in rec.labels


# ---------------------------------------------------------------------------
# 7. MouseStateManager 単体テスト
# ---------------------------------------------------------------------------

class TestMouseStateManager:

    def test_suppress_single_button(self):
        state = MouseStateManager()
        state.add_suppress_group([MouseButton.RIGHT])
        assert state.should_suppress_single(MouseButton.RIGHT) is True
        assert state.should_suppress_single(MouseButton.RIGHT) is False

    def test_suppress_clears_after_use(self):
        state = MouseStateManager()
        state.add_suppress_group([MouseButton.LEFT, MouseButton.RIGHT])
        assert state.should_suppress_single(MouseButton.LEFT) is True
        assert state.should_suppress_single(MouseButton.RIGHT) is True
        assert state.should_suppress_single(MouseButton.LEFT) is False

    def test_clear_suppress_groups(self):
        state = MouseStateManager()
        state.add_suppress_group([MouseButton.LEFT])
        state.clear_suppress_groups()
        assert state.should_suppress_single(MouseButton.LEFT) is False

    def test_press_position_lifecycle(self):
        state = MouseStateManager()
        w = QtWidgets.QWidget()
        pos = QtCore.QPoint(100, 200)
        state.set_press_position(w, pos)
        assert state.get_press_position(w) == pos
        state.clear_press_position(w)
        assert state.get_press_position(w) is None

    def test_double_click_button_lifecycle(self):
        state = MouseStateManager()
        w = QtWidgets.QWidget()
        state.set_double_click_button(w, LMB)
        assert state.get_double_click_button(w) == LMB
        state.clear_double_click_button(w)
        assert state.get_double_click_button(w) is None


# ---------------------------------------------------------------------------
# 8. MouseEventManager.execute_action の suppress 連携
# ---------------------------------------------------------------------------

class TestExecuteActionSuppress:

    def test_single_without_held_is_suppressed(self):
        mgr = MouseEventManager()
        state = MouseStateManager.instance()
        recorder = ActionRecorder()

        key_single = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE)
        mgr.bind(key_single, recorder.make_handler("L_SINGLE"))

        state.add_suppress_group([MouseButton.LEFT])
        mgr.execute_action(key_single)
        assert recorder.labels == []

    def test_single_with_held_adds_suppress(self):
        mgr = MouseEventManager()
        state = MouseStateManager.instance()
        recorder = ActionRecorder()

        key_held = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, held_buttons=(MouseButton.RIGHT,))
        mgr.bind(key_held, recorder.make_handler("L_HELD_R"))

        mgr.execute_action(key_held)
        assert recorder.labels == ["L_HELD_R"]
        assert state.should_suppress_single(MouseButton.RIGHT) is True


# ---------------------------------------------------------------------------
# 9. MouseActionKey の一致・不一致
# ---------------------------------------------------------------------------

class TestMouseActionKeyEquality:

    def test_same_key_equals(self):
        a = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE)
        b = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE)
        assert a == b
        assert hash(a) == hash(b)

    def test_different_button_not_equal(self):
        a = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE)
        b = MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE)
        assert a != b

    def test_held_order_irrelevant(self):
        a = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, held_buttons=(MouseButton.RIGHT, MouseButton.MIDDLE))
        b = MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, held_buttons=(MouseButton.MIDDLE, MouseButton.RIGHT))
        assert a == b
        assert hash(a) == hash(b)

    def test_from_dict_roundtrip(self):
        key = MouseActionKey(MouseButton.LEFT, ClickType.DOUBLE, held_buttons=(MouseButton.RIGHT,))
        d = key.to_dict()
        restored = MouseActionKey.from_dict(d)
        assert key == restored


# ---------------------------------------------------------------------------
# 10. _make_click_key がイベントから正しいキーを生成するか
# ---------------------------------------------------------------------------

class TestMakeClickKey:

    def test_simple_left_single(self):
        ev = _release(LMB)
        key = MouseEventManager._make_click_key(ev, False)
        assert key.button == MouseButton.LEFT
        assert key.click_type == ClickType.SINGLE
        assert key.held_buttons == frozenset()

    def test_left_release_with_right_held(self):
        ev = _release(LMB, buttons_held=RMB)
        key = MouseEventManager._make_click_key(ev, False)
        assert key.button == MouseButton.LEFT
        assert key.click_type == ClickType.SINGLE
        assert MouseButton.RIGHT in key.held_buttons

    def test_double_click_flag(self):
        ev = _release(LMB)
        key = MouseEventManager._make_click_key(ev, True)
        assert key.click_type == ClickType.DOUBLE


# ---------------------------------------------------------------------------
# 11. get_held_buttons: exclude が正しく機能するか
# ---------------------------------------------------------------------------

class TestGetHeldButtons:

    def test_excludes_pressed_button(self):
        buttons = LMB | RMB
        held = MouseEventManager.get_held_buttons(buttons, exclude=MouseButton.LEFT)
        assert MouseButton.LEFT not in held
        assert MouseButton.RIGHT in held

    def test_no_exclude(self):
        buttons = LMB | RMB
        held = MouseEventManager.get_held_buttons(buttons)
        assert MouseButton.LEFT in held
        assert MouseButton.RIGHT in held


# ---------------------------------------------------------------------------
# 12. パラメトライズ: 各種シーケンスの最終状態検証
# ---------------------------------------------------------------------------

PRESS = QtCore.QEvent.Type.MouseButtonPress
RELEASE = QtCore.QEvent.Type.MouseButtonRelease


class _Step:
    def __init__(self, action, button, buttons_held=NO_BTN, mods=NO_MOD):
        self.action = action
        self.button = button
        self.buttons_held = buttons_held
        self.mods = mods


P = lambda btn, held=NO_BTN, mods=NO_MOD: _Step("press", btn, held, mods)
R = lambda btn, held=NO_BTN, mods=NO_MOD: _Step("release", btn, held, mods)


SEQUENCE_SCENARIOS = [
    pytest.param(
        [P(LMB), R(LMB)],
        ["L_SINGLE"],
        id="left_click",
    ),
    pytest.param(
        [P(RMB), R(RMB)],
        ["R_SINGLE"],
        id="right_click",
    ),
    pytest.param(
        [P(RMB), P(LMB, RMB), R(LMB, RMB), R(RMB)],
        ["L_HELD_R"],
        id="right_hold_left_click",
    ),
    pytest.param(
        [P(LMB), P(RMB, LMB), R(RMB, LMB), R(LMB)],
        ["R_HELD_L"],
        id="left_hold_right_click",
    ),
    pytest.param(
        [P(RMB), R(RMB), P(LMB), R(LMB)],
        ["R_SINGLE", "L_SINGLE"],
        id="sequential_right_then_left",
    ),
    pytest.param(
        [P(LMB), R(LMB), P(RMB), R(RMB)],
        ["L_SINGLE", "R_SINGLE"],
        id="sequential_left_then_right",
    ),
]


ALL_BINDINGS = {
    MouseActionKey(MouseButton.LEFT, ClickType.SINGLE): "L_SINGLE",
    MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
    MouseActionKey(MouseButton.MIDDLE, ClickType.SINGLE): "M_SINGLE",
    MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, held_buttons=(MouseButton.RIGHT,)): "L_HELD_R",
    MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, held_buttons=(MouseButton.LEFT,)): "R_HELD_L",
    MouseActionKey(MouseButton.LEFT, ClickType.DOUBLE): "L_DOUBLE",
    MouseActionKey(MouseButton.RIGHT, ClickType.DOUBLE): "R_DOUBLE",
}


@pytest.mark.parametrize("steps, expected_actions", SEQUENCE_SCENARIOS)
def test_event_sequence(qtbot, steps, expected_actions):
    w, rec = _setup_widget(qtbot, ALL_BINDINGS)
    d = w._mouse_dispatcher
    with patch.object(d, "_find_target_widget", return_value=w):
        for step in steps:
            if step.action == "press":
                _inject_press(d, w, step.button, step.buttons_held, step.mods)
            elif step.action == "release":
                _inject_release(d, w, step.button, step.buttons_held, step.mods)
    assert rec.labels == expected_actions


# ---------------------------------------------------------------------------
# 13. 状態クリーンアップ: シーケンス後に内部状態が汚染されていないか
# ---------------------------------------------------------------------------

class TestStateCleanupAfterSequence:

    def _run_sequence_and_check_clean(self, qtbot, steps):
        w, rec = _setup_widget(qtbot, ALL_BINDINGS)
        d = w._mouse_dispatcher
        state = d._state
        with patch.object(d, "_find_target_widget", return_value=w):
            for step in steps:
                if step.action == "press":
                    _inject_press(d, w, step.button, step.buttons_held, step.mods)
                elif step.action == "release":
                    _inject_release(d, w, step.button, step.buttons_held, step.mods)

        assert d._dragging_button is None
        assert state.get_press_position(w) is None
        assert state.get_internal_drag_context(w) is None

    def test_clean_after_left_click(self, qtbot):
        self._run_sequence_and_check_clean(qtbot, [P(LMB), R(LMB)])

    def test_clean_after_right_click(self, qtbot):
        self._run_sequence_and_check_clean(qtbot, [P(RMB), R(RMB)])

    def test_clean_after_right_hold_left(self, qtbot):
        self._run_sequence_and_check_clean(qtbot, [
            P(RMB), P(LMB, RMB), R(LMB, RMB), R(RMB),
        ])

    def test_clean_after_left_hold_right(self, qtbot):
        self._run_sequence_and_check_clean(qtbot, [
            P(LMB), P(RMB, LMB), R(RMB, LMB), R(LMB),
        ])

    def test_clean_after_reversed_release_order(self, qtbot):
        self._run_sequence_and_check_clean(qtbot, [
            P(RMB), P(LMB, RMB), R(RMB, LMB), R(LMB),
        ])


# ---------------------------------------------------------------------------
# 14. 連続操作: 前回の操作が次回に影響しないこと
# ---------------------------------------------------------------------------

class TestConsecutiveOperations:

    def test_left_click_after_right_hold_left(self, qtbot):
        w, rec = _setup_widget(qtbot, ALL_BINDINGS)
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_press(d, w, LMB, RMB)
            _inject_release(d, w, LMB, RMB)
            _inject_release(d, w, RMB)
            rec.clear()

            _inject_press(d, w, LMB)
            _inject_release(d, w, LMB)
            assert rec.labels == ["L_SINGLE"]

    def test_right_click_after_left_hold_right(self, qtbot):
        w, rec = _setup_widget(qtbot, ALL_BINDINGS)
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, LMB)
            _inject_press(d, w, RMB, LMB)
            _inject_release(d, w, RMB, LMB)
            _inject_release(d, w, LMB)
            rec.clear()

            _inject_press(d, w, RMB)
            _inject_release(d, w, RMB)
            assert rec.labels == ["R_SINGLE"]

    def test_multiple_left_clicks_independent(self, qtbot):
        w, rec = _setup_widget(qtbot, ALL_BINDINGS)
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            for _ in range(3):
                _inject_press(d, w, LMB)
                _inject_release(d, w, LMB)
            assert rec.labels == ["L_SINGLE", "L_SINGLE", "L_SINGLE"]


# ---------------------------------------------------------------------------
# 15. _find_target_widget が None を返した場合の安全性
# ---------------------------------------------------------------------------

class TestNullTargetWidget:

    def test_release_with_no_target_cleans_up(self, qtbot):
        w, rec = _setup_widget(qtbot, ALL_BINDINGS)
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=None):
            _inject_press(d, w, LMB)
            _inject_release(d, w, LMB)
        assert rec.labels == []
        assert d._dragging_button is None

    def test_release_with_no_target_doesnt_corrupt_next_click(self, qtbot):
        w, rec = _setup_widget(qtbot, ALL_BINDINGS)
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=None):
            _inject_press(d, w, RMB)
            _inject_release(d, w, RMB)
        assert rec.labels == []

        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, LMB)
            _inject_release(d, w, LMB)
        assert rec.labels == ["L_SINGLE"]


# ---------------------------------------------------------------------------
# 16. map_qt_button
# ---------------------------------------------------------------------------

class TestMapQtButton:

    @pytest.mark.parametrize("qt_btn, expected", [
        (LMB, MouseButton.LEFT),
        (RMB, MouseButton.RIGHT),
        (MMB, MouseButton.MIDDLE),
        (QtCore.Qt.XButton1, MouseButton.X1),
        (QtCore.Qt.XButton2, MouseButton.X2),
        (NO_BTN, MouseButton.NONE),
    ])
    def test_map(self, qt_btn, expected):
        assert MouseEventManager.map_qt_button(qt_btn) == expected


# ---------------------------------------------------------------------------
# 17. get_modifiers
# ---------------------------------------------------------------------------

class TestGetModifiers:

    def test_no_modifiers(self):
        from wayfer.core.actions.binding.mouse.types import ModifierKey
        mods = MouseEventManager.get_modifiers(NO_MOD)
        assert mods == ()

    def test_ctrl(self):
        from wayfer.core.actions.binding.mouse.types import ModifierKey
        mods = MouseEventManager.get_modifiers(CTRL)
        assert ModifierKey.CTRL in mods

    def test_ctrl_shift(self):
        from wayfer.core.actions.binding.mouse.types import ModifierKey
        mods = MouseEventManager.get_modifiers(CTRL | SHIFT)
        assert ModifierKey.CTRL in mods
        assert ModifierKey.SHIFT in mods


# ---------------------------------------------------------------------------
# 18. ホイール + held_buttons サプレステスト
# ---------------------------------------------------------------------------

def _wheel_event(angle_y: int, buttons=NO_BTN, mods=NO_MOD):
    return QtGui.QWheelEvent(
        QtCore.QPointF(50, 50),
        QtCore.QPointF(50, 50),
        QtCore.QPoint(0, 0),
        QtCore.QPoint(0, angle_y),
        buttons,
        mods,
        QtCore.Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def _inject_wheel(disp, widget, angle_y, buttons=NO_BTN, mods=NO_MOD):
    disp._state._processed_events.clear()
    ev = _wheel_event(angle_y, buttons, mods)
    disp.eventFilter(widget, ev)


class TestWheelWithHeldButtonSuppression:

    def test_right_hold_wheel_suppresses_right_single(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, held_buttons=(MouseButton.RIGHT,)): "WHEEL_HELD_R",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_wheel(d, w, 120, buttons=RMB)
            assert "WHEEL_HELD_R" in rec.labels

            rec.clear()
            _inject_release(d, w, RMB)
            assert "R_SINGLE" not in rec.labels

    def test_right_hold_wheel_down_suppresses_right_single(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_DOWN, held_buttons=(MouseButton.RIGHT,)): "WDOWN_HELD_R",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_wheel(d, w, -120, buttons=RMB)
            assert "WDOWN_HELD_R" in rec.labels

            rec.clear()
            _inject_release(d, w, RMB)
            assert "R_SINGLE" not in rec.labels

    def test_wheel_without_held_does_not_suppress(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP): "WHEEL_PLAIN",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_wheel(d, w, 120)
            assert "WHEEL_PLAIN" in rec.labels

            rec.clear()
            _inject_press(d, w, RMB)
            _inject_release(d, w, RMB)
            assert "R_SINGLE" in rec.labels

    def test_right_hold_multiple_wheels_suppresses_once(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, held_buttons=(MouseButton.RIGHT,)): "WHEEL_HELD_R",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_wheel(d, w, 120, buttons=RMB)
            _inject_wheel(d, w, 120, buttons=RMB)
            _inject_wheel(d, w, 120, buttons=RMB)
            assert rec.labels.count("WHEEL_HELD_R") == 3

            rec.clear()
            _inject_release(d, w, RMB)
            assert "R_SINGLE" not in rec.labels

    def test_next_right_click_works_after_suppression(self, qtbot):
        w, rec = _setup_widget(qtbot, {
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE): "R_SINGLE",
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, held_buttons=(MouseButton.RIGHT,)): "WHEEL_HELD_R",
        })
        d = w._mouse_dispatcher
        with patch.object(d, "_find_target_widget", return_value=w):
            _inject_press(d, w, RMB)
            _inject_wheel(d, w, 120, buttons=RMB)
            rec.clear()
            _inject_release(d, w, RMB)
            assert "R_SINGLE" not in rec.labels

            rec.clear()
            _inject_press(d, w, RMB)
            _inject_release(d, w, RMB)
            assert "R_SINGLE" in rec.labels
