from ...command.core import CommandRegistry
from ...command.context import CommandContext


class DragContext:
    def __init__(self):
        self.cancelled = False

    def on_move(self, event):
        pass

    def on_end(self, event):
        pass

    def on_enter(self, event):
        pass

    def on_leave(self, event):
        pass

    def on_drop(self, event):
        pass


class ExternalDropDynamicContext(DragContext):
    def __init__(self, widget, registry, resolver):
        super().__init__()
        self.widget = widget
        self.registry = registry
        self.resolver = resolver
        self._active_payload = None
        self._active_key = None

    def _exec(self, payload, suffix: str, event):
        if not payload:
            return False
        base_id = getattr(payload, "id", None)
        if not base_id:
            return False
        cmd_class = self.registry.get_command(base_id)
        if not cmd_class:
            return False
        meta = cmd_class.meta
        callbacks = meta.drop_callbacks or {} if meta else {}
        if "drop" not in callbacks:
            return False
        args = dict(getattr(payload, "args", None) or {})
        ctx = CommandContext.create(self.widget, None, source="drop", event=event, extras={"context": self, "phase": str(suffix)})
        self.registry.execute(base_id, ctx=ctx, **args)
        return True

    def _switch_if_needed(self, payload, key, event, allow_enter: bool):
        if self._active_payload is payload and self._active_key == key:
            return
        if self._active_payload is not None and self._active_key is not None:
            self._exec(self._active_payload, "leave", event)
        self._active_payload = payload
        self._active_key = key
        if allow_enter and self._active_payload is not None and self._active_key is not None:
            self._exec(self._active_payload, "enter", event)

    def on_enter(self, event):
        payload, key = self.resolver(event)
        self._active_payload = payload
        self._active_key = key
        return self._exec(payload, "enter", event)

    def on_move(self, event):
        payload, key = self.resolver(event)
        self._switch_if_needed(payload, key, event, allow_enter=True)
        return self._exec(self._active_payload, "move", event)

    def on_leave(self, event):
        if self._active_payload is None or self._active_key is None:
            return False
        ok = self._exec(self._active_payload, "leave", event)
        self._active_payload = None
        self._active_key = None
        return ok

    def on_drop(self, event):
        payload, key = self.resolver(event)
        if payload is not self._active_payload or key != self._active_key:
            if self._active_payload is not None and self._active_key is not None:
                self._exec(self._active_payload, "leave", event)
            self._active_payload = payload
            self._active_key = key
        ok = self._exec(self._active_payload, "drop", event)
        self._active_payload = None
        self._active_key = None
        return ok


class CommandDragContext(DragContext):
    def __init__(self, base_id, registry, widget, args=None):
        super().__init__()
        self.base_id = base_id
        self.registry = registry
        self.widget = widget
        self.args = args or {}

    def _dispatch(self, phase: str, source: str, callback_attr: str, event):
        cmd_class = self.registry.get_command(self.base_id)
        meta = cmd_class.meta if cmd_class else None
        if meta and phase in (getattr(meta, callback_attr, None) or {}):
            ctx = CommandContext.create(self.widget, None, source=source, event=event, extras={"context": self, "phase": phase})
            self.registry.execute(self.base_id, ctx=ctx, **self.args)

    def on_move(self, event):
        self._dispatch("move", "drag", "drag_callbacks", event)

    def on_end(self, event):
        self._dispatch("end", "drag", "drag_callbacks", event)

    def on_enter(self, event):
        self._dispatch("enter", "drop", "drop_callbacks", event)

    def on_leave(self, event):
        self._dispatch("leave", "drop", "drop_callbacks", event)

    def on_drop(self, event):
        self._dispatch("drop", "drop", "drop_callbacks", event)
