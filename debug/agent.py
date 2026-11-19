import itertools
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import msgpack
from PySide6 import QtCore, QtWidgets

from debug import qt_inspect
from wafer.core.common.profile import current_profile
from wafer.core.ipc.message import Message
from wafer.core.ipc.node import Node
from wafer.core.logs import AppLogger

AGENT_ROLE = "debug_agent"
CALL_TOPIC = "debug.call"


class DebugAgent(QtCore.QObject):
    def __init__(self, process_role: str, node: Node, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._role = process_role
        self._node = node
        self._pending: dict[int, tuple[Message, float]] = {}
        self._pending_lock = threading.Lock()
        self._keys = itertools.count()
        self._stopped = False
        self._ops: dict[str, Callable[..., Any]] = {
            "ping": self._ping,
            "screenshot": qt_inspect.screenshot,
            "get_state": qt_inspect.get_state,
            "widget_tree": qt_inspect.widget_tree,
            "get_property": qt_inspect.get_property,
            "list_commands": qt_inspect.list_commands,
            "run_command": qt_inspect.run_command,
            "modal_state": qt_inspect.modal_state,
            "modal_input": qt_inspect.modal_input,
            "modal_click": qt_inspect.modal_click,
            "click": qt_inspect.click,
            "type_text": qt_inspect.type_text,
            "key": qt_inspect.key,
        }
        node.subscribe(CALL_TOPIC, self._on_call)

    @property
    def node(self) -> Node:
        return self._node

    def start(self) -> None:
        self._node.start()
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.stop)
        AppLogger.info(f"[debug] agent {self._node.node_id} is listening for {CALL_TOPIC} ({self._role}, profile={self._node.profile})")

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        app = QtWidgets.QApplication.instance()
        if app is not None:
            try:
                app.aboutToQuit.disconnect(self.stop)
            except (RuntimeError, TypeError) as e:
                AppLogger.debug(f"[debug] agent was not connected to aboutToQuit: {e}")
        self._node.unsubscribe(CALL_TOPIC)
        self._node.stop()

    def call(self, op: str, args: dict, *, received: float | None = None) -> dict:
        handler = self._handler(op, time.perf_counter() if received is None else received)
        try:
            if handler is None:
                raise LookupError(f"unknown debug op {op!r}")
            if not isinstance(args, dict):
                raise TypeError(f"args of {op!r} must be a dict, not {type(args).__name__}")
            result = handler(**args)
            if not isinstance(result, bytes):
                msgpack.packb(result, use_bin_type=True)
            return {"ok": True, "result": result, "error": ""}
        except Exception as e:
            AppLogger.warning(f"[debug] op {op!r} failed: {type(e).__name__}: {e}", exc=e)
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}

    def _handler(self, op: str, received: float) -> Callable[..., Any] | None:
        if op == "idle":
            return lambda: self._idle(received)
        return self._ops.get(op)

    def _ping(self) -> dict:
        return {"pid": os.getpid(), "role": self._role, "profile": self._node.profile}

    def _idle(self, received: float) -> dict:
        return {"modal": qt_inspect.active_modal() is not None, "main_thread_ms": (time.perf_counter() - received) * 1000.0}

    def _on_call(self, msg: Message) -> bool:
        key = next(self._keys)
        with self._pending_lock:
            self._pending[key] = (msg, time.perf_counter())
        try:
            QtCore.QMetaObject.invokeMethod(self, "_run_call", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, key))
        except Exception as e:
            with self._pending_lock:
                self._pending.pop(key, None)
            AppLogger.warning("[debug] could not hand a debug.call over to the GUI thread", exc=e)
            self._node.enqueue(msg.reply({"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}))
        return True

    @QtCore.Slot(int)
    def _run_call(self, key: int) -> None:
        with self._pending_lock:
            msg, received = self._pending.pop(key)
        payload = msg.payload if isinstance(msg.payload, dict) else {}
        reply = self.call(str(payload.get("op", "")), payload.get("args", {}), received=received)
        self._node.enqueue(msg.reply(reply))


def attach(process_role: str) -> DebugAgent:
    agent = DebugAgent(process_role, Node(AGENT_ROLE, profile=current_profile()), parent=QtWidgets.QApplication.instance())
    agent.start()
    return agent
