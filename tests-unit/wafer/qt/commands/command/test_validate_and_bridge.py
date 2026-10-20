import pytest
from unittest.mock import MagicMock

from wafer.qt.commands.command.core import (
    CommandMeta,
    CommandParam,
    CommandRegistry,
    create_command_from_meta,
    register_command_defs,
)
from wafer.qt.commands.command.menu import normalize_command_meta
from wafer.qt.commands.command.state import CommandOptionStore


@pytest.fixture(autouse=True)
def _isolate_registry():
    reg = CommandRegistry.instance()
    prev = dict(reg._commands)
    yield
    reg._commands = prev


@pytest.fixture(autouse=True)
def _isolate_option_store(tmp_path):
    store = CommandOptionStore.configure(tmp_path / "opts.json")
    yield
    store._reconfigure(tmp_path / "opts.json")


def _register(meta):
    normalize_command_meta([], meta)
    register_command_defs([meta])
    return meta


class TestBridgeCommand:
    def _import_bridge(self):
        from wafer.qt.commands.bridge import Command, Context

        return Command, Context

    def test_run_no_params(self):
        called = {}
        meta = CommandMeta(path="t.nop", display="Nop", func=lambda ctx: called.update(ran=True))
        _register(meta)
        Command, _ = self._import_bridge()
        Command.run("t.nop")
        assert called.get("ran")

    def test_run_with_params(self):
        results = {}

        def fn(ctx, step: int = 1):
            results["step"] = step

        meta = CommandMeta(path="t.stepped", display="S", func=fn, params=[CommandParam(name="step", value=1)])
        _register(meta)
        Command, _ = self._import_bridge()
        Command.run("t.stepped", {"step": 5})
        assert results["step"] == 5

    def test_run_missing_param_raises(self):
        meta = CommandMeta(path="t.req", display="R", func=lambda ctx, x=0: x, params=[CommandParam(name="x", value=0)])
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Missing args"):
            Command.run("t.req", {})

    def test_run_extra_param_raises(self):
        meta = CommandMeta(path="t.nop2", display="N2", func=lambda ctx: None)
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Unknown args"):
            Command.run("t.nop2", {"bogus": 1})

    def test_run_unknown_command_returns_none(self):
        Command, _ = self._import_bridge()
        result = Command.run("nonexistent.cmd")
        assert result is None

    def test_run_type_error(self):
        meta = CommandMeta(path="t.typed", display="T", func=lambda ctx, n=0: n, params=[CommandParam(name="n", value=0)])
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(TypeError, match="expected int"):
            Command.run("t.typed", {"n": "bad"})

    def test_get_args_defaults(self):
        meta = CommandMeta(
            path="t.defs",
            display="D",
            func=lambda ctx, a=1, b=True: None,
            params=[CommandParam(name="a", value=1), CommandParam(name="b", value=True)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        assert Command.get_args("t.defs") == {"a": 1, "b": True}

    def test_get_args_unknown_raises(self):
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Command not found"):
            Command.get_args("nonexistent.cmd")

    def test_get_args_no_params(self):
        meta = CommandMeta(path="t.nop3", display="N3", func=lambda ctx: None)
        _register(meta)
        Command, _ = self._import_bridge()
        assert Command.get_args("t.nop3") == {}

    def test_set_args_and_get_args(self):
        meta = CommandMeta(
            path="t.opts",
            display="O",
            func=lambda ctx, x=1, y=2.0: None,
            params=[CommandParam(name="x", value=1), CommandParam(name="y", value=2.0)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        Command.set_args("t.opts", {"x": 99})
        result = Command.get_args("t.opts")
        assert result["x"] == 99
        assert result["y"] == 2.0

    def test_set_args_full_overwrite(self):
        meta = CommandMeta(
            path="t.full",
            display="F",
            func=lambda ctx, a=0, b=0: None,
            params=[CommandParam(name="a", value=0), CommandParam(name="b", value=0)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        Command.set_args("t.full", {"a": 10, "b": 20})
        assert Command.get_args("t.full") == {"a": 10, "b": 20}

    def test_set_args_unknown_command_raises(self):
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Command not found"):
            Command.set_args("nonexistent.cmd", {"x": 1})

    def test_set_args_extra_key_raises(self):
        meta = CommandMeta(path="t.clean", display="C", func=lambda ctx: None)
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Unknown args"):
            Command.set_args("t.clean", {"nope": 1})

    def test_set_args_type_error(self):
        meta = CommandMeta(
            path="t.typerr",
            display="TE",
            func=lambda ctx, n=0: None,
            params=[CommandParam(name="n", value=0)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(TypeError, match="expected int"):
            Command.set_args("t.typerr", {"n": "bad"})

    def test_set_args_cleans_stale_keys(self):
        meta = CommandMeta(
            path="t.stale",
            display="S",
            func=lambda ctx, a=0: None,
            params=[CommandParam(name="a", value=0)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        store = CommandOptionStore.instance()
        store.set("t.stale", {"a": 1, "old_removed": 99})
        store.commit()
        Command.set_args("t.stale", {"a": 5})
        result = Command.get_args("t.stale")
        assert result == {"a": 5}

    def test_run_then_get_args_independent(self):
        results = {}

        def fn(ctx, v=0):
            results["v"] = v

        meta = CommandMeta(path="t.indep", display="I", func=fn, params=[CommandParam(name="v", value=0)])
        _register(meta)
        Command, _ = self._import_bridge()
        Command.set_args("t.indep", {"v": 100})
        Command.run("t.indep", {"v": 999})
        assert results["v"] == 999
        assert Command.get_args("t.indep")["v"] == 100

    def test_run_with_extras(self):
        captured = {}

        def fn(ctx):
            captured["foo"] = ctx.get("foo")
            captured["source"] = ctx._source

        meta = CommandMeta(path="t.ext", display="E", func=fn)
        _register(meta)
        Command, _ = self._import_bridge()
        Command.run("t.ext", extras={"foo": "bar"})
        assert captured["foo"] == "bar"
        assert captured["source"] == "run"

    def test_run_drag_command_without_event_raises(self):
        meta = CommandMeta(
            path="t.dragcmd",
            display="Drag",
            category="drag",
            drag_callbacks={"start": lambda ctx: None, "move": lambda ctx: None, "end": lambda ctx: None},
            target_widgets=["TestWidget"],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="requires event"):
            Command.run("t.dragcmd")

    def test_run_drop_command_without_event_raises(self):
        meta = CommandMeta(
            path="t.dropcmd",
            display="Drop",
            category="drop",
            drop_callbacks={"enter": lambda ctx: None, "leave": lambda ctx: None, "drop": lambda ctx: None},
            target_widgets=["TestWidget"],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="requires event"):
            Command.run("t.dropcmd")


class TestInvokeRequiredParams:
    def _import_bridge(self):
        from wafer.qt.commands.bridge import Command, Context

        return Command, Context

    def test_invoke_required_missing_returns_none(self, monkeypatch):
        called = {}
        meta = CommandMeta(
            path="t.reqp",
            display="RP",
            func=lambda ctx, session="": called.update(ran=True),
            params=[CommandParam(name="session", value=lambda: ["A", "B"], required=True)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        monkeypatch.setattr(Command, "_show_options_for_required", lambda *a, **kw: None)
        result = Command.invoke("t.reqp")
        assert result is None
        assert "ran" not in called

    def test_invoke_required_supplied_executes(self):
        captured = {}

        def fn(ctx, session=""):
            captured["session"] = session

        meta = CommandMeta(
            path="t.reqfill",
            display="RF",
            func=fn,
            params=[CommandParam(name="session", value=lambda: ["A", "B"], required=True)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        Command.invoke("t.reqfill", session="A")
        assert captured["session"] == "A"


class TestIsValueSatisfied:
    def test_static_choices_truthy(self):
        p = CommandParam(name="x", value=("a", "b"))
        assert p.is_value_satisfied("a") is True
        assert p.is_value_satisfied("anything") is True

    def test_empty_or_none(self):
        p = CommandParam(name="x", value=lambda: ["a", "b"])
        assert p.is_value_satisfied("") is False
        assert p.is_value_satisfied(None) is False

    def test_dynamic_value_in_current_list(self):
        p = CommandParam(name="x", value=lambda: ["a", "b"])
        assert p.is_value_satisfied("a") is True

    def test_dynamic_value_not_in_current_list(self):
        p = CommandParam(name="x", value=lambda: ["a", "b"])
        assert p.is_value_satisfied("c") is False

    def test_dynamic_choices_fn_error_returns_true(self):
        def boom():
            raise RuntimeError("boom")

        p = CommandParam(name="x", value=boom)
        assert p.is_value_satisfied("anything") is True


class TestInvokeStaleStoredValue:
    def _import_bridge(self):
        from wafer.qt.commands.bridge import Command, Context

        return Command, Context

    def test_stale_stored_value_triggers_dialog_and_clears(self, monkeypatch):
        called = {}
        meta = CommandMeta(
            path="t.stale",
            display="ST",
            func=lambda ctx, name="": called.update(ran=name),
            params=[CommandParam(name="name", value=lambda: ["A", "B"], required=True)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        Command.set_args("t.stale", {"name": "GHOST"})
        assert Command.get_args("t.stale") == {"name": "GHOST"}

        shown = {}

        def fake_show(cid, cls, extras, *, ctx=None, parent=None):
            shown["cid"] = cid

        monkeypatch.setattr(Command, "_show_options_for_required", fake_show)
        result = Command.invoke("t.stale")
        assert result is None
        assert shown["cid"] == "t.stale"
        assert "ran" not in called

    def test_fresh_stored_value_executes_without_dialog(self):
        captured = {}

        def fn(ctx, name=""):
            captured["name"] = name

        meta = CommandMeta(
            path="t.fresh",
            display="FR",
            func=fn,
            params=[CommandParam(name="name", value=lambda: ["A", "B"], required=True)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        Command.set_args("t.fresh", {"name": "A"})
        Command.invoke("t.fresh")
        assert captured["name"] == "A"


class TestShowOptionsForRequiredAutoPersist:
    def _import_bridge(self):
        from wafer.qt.commands.bridge import Command, Context

        return Command, Context

    def test_clears_stale_before_dialog(self, monkeypatch):
        meta = CommandMeta(
            path="t.clear",
            display="CL",
            func=lambda ctx, name="": None,
            params=[CommandParam(name="name", value=lambda: ["A"], required=True)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        Command.set_args("t.clear", {"name": "GHOST"})

        opened = {}

        class FakeDialog:
            def __init__(self, cls, parent, execute_callback=None, auto_required=False, **kw):
                opened["auto_required"] = auto_required

            def exec(self):
                return 0

        from wafer.qt.commands.command import option_dialog as od

        monkeypatch.setattr(od, "CommandOptionsDialog", FakeDialog)
        cmd_class = CommandRegistry.instance().get_command("t.clear")
        Command._show_options_for_required("t.clear", cmd_class, None)
        assert opened["auto_required"] is True
        assert Command.get_args("t.clear") == {"name": ""}

    def test_exec_callback_persists_and_runs(self, monkeypatch):
        captured = {}

        def fn(ctx, name=""):
            captured["name"] = name

        meta = CommandMeta(
            path="t.persist",
            display="P",
            func=fn,
            params=[CommandParam(name="name", value=lambda: ["A", "B"], required=True)],
        )
        _register(meta)
        Command, _ = self._import_bridge()

        class FakeDialog:
            def __init__(self, cls, parent, execute_callback=None, auto_required=False, **kw):
                self._cb = execute_callback

            def exec(self):
                self._cb({"name": "B"})
                return 1

        from wafer.qt.commands.command import option_dialog as od

        monkeypatch.setattr(od, "CommandOptionsDialog", FakeDialog)

        cmd_class = CommandRegistry.instance().get_command("t.persist")
        Command._show_options_for_required("t.persist", cmd_class, None)
        assert captured["name"] == "B"
        assert Command.get_args("t.persist") == {"name": "B"}


class TestNonPersistedParams:
    def _register_transient(self, captured):
        def fn(ctx, target="", remember=False):
            captured.update(target=target, remember=remember)

        return _register(
            CommandMeta(
                path="t.transient",
                display="TR",
                func=fn,
                params=[
                    CommandParam(name="target", value="", required=True, persist=False),
                    CommandParam(name="remember", value=False),
                ],
            )
        )

    def test_param_persists_by_default(self):
        assert CommandParam(name="x", value=0).persist is True

    def test_set_args_does_not_store_non_persisted_params(self):
        from wafer.qt.commands.bridge import Command

        self._register_transient({})
        Command.set_args("t.transient", {"target": "F:/a.png", "remember": True})
        assert CommandOptionStore.instance().get("t.transient").args == {"remember": True}
        assert Command.get_args("t.transient") == {"target": "", "remember": True}

    def test_required_dialog_value_reaches_the_run_but_is_not_stored(self, monkeypatch):
        from wafer.qt.commands.bridge import Command
        from wafer.qt.commands.command import option_dialog as od

        captured = {}
        self._register_transient(captured)

        class FakeDialog:
            def __init__(self, cls, parent, execute_callback=None, auto_required=False, **kw):
                self._cb = execute_callback

            def exec(self):
                self._cb({"target": "F:/a.png", "remember": True})
                return 1

        monkeypatch.setattr(od, "CommandOptionsDialog", FakeDialog)
        Command.invoke("t.transient")
        assert captured == {"target": "F:/a.png", "remember": True}
        assert Command.get_args("t.transient") == {"target": "", "remember": True}

        captured.clear()
        asked = []
        monkeypatch.setattr(Command, "_show_options_for_required", staticmethod(lambda command_id, *a, **k: asked.append(command_id)))
        Command.invoke("t.transient")
        assert asked == ["t.transient"]
        assert captured == {}

    def test_menu_options_dialog_does_not_store_non_persisted_params(self, qtbot, monkeypatch):
        from PySide6 import QtWidgets

        from wafer.qt.commands.command import menu_builder

        captured = {}
        self._register_transient(captured)

        class FakeDialog:
            def __init__(self, cls, parent, execute_callback=None, binding_mode=False, **kw):
                self._cb = execute_callback

            def exec(self):
                self._cb(self.get_values())
                return QtWidgets.QDialog.Accepted

            def did_save(self):
                return True

            def get_values(self):
                return {"target": "F:/a.png", "remember": True}

        monkeypatch.setattr(menu_builder, "CommandOptionsDialog", FakeDialog)
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        menu_builder.CommandMenuBuilder.instance()._show_options("t.transient", parent)
        assert captured == {"target": "F:/a.png", "remember": True}
        assert CommandOptionStore.instance().get("t.transient").args == {"remember": True}
