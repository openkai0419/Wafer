import pytest
from unittest.mock import MagicMock
from wayfer.core.actions.command.require import require, require_v


def _make_ctx(instances=None, values=None):
    ctx = MagicMock()
    _instances = dict(instances or {})
    _values = dict(values or {})
    ctx.get_instance = MagicMock(side_effect=lambda name: _instances.get(name))
    ctx.get = MagicMock(side_effect=lambda key, default=None: _values.get(key, default))
    return ctx


class TestRequire:
    def test_injects_instance(self):
        sm = MagicMock()
        ctx = _make_ctx(instances={"SlotManager": sm})

        @require(sm="SlotManager")
        def cmd(ctx, sm):
            return sm

        assert cmd(ctx) is sm

    def test_returns_none_when_missing(self):
        ctx = _make_ctx()

        @require(sm="SlotManager")
        def cmd(ctx, sm):
            return sm

        assert cmd(ctx) is None

    def test_notifies_on_missing(self):
        ctx = _make_ctx()

        @require(sm="SlotManager")
        def cmd(ctx, sm):
            return sm

        with pytest.MonkeyPatch.context() as mp:
            warned = []
            mp.setattr(
                "wayfer.core.actions.command.require.Notifier",
                type("FakeNotifier", (), {"warning": staticmethod(lambda msg: warned.append(msg))}),
            )
            cmd(ctx)
            assert any("SlotManager" in w for w in warned)

    def test_multiple_instances(self):
        view = MagicMock()
        items = MagicMock()
        ctx = _make_ctx(instances={"GridView": view, "GridItemModel": items})

        @require(view="GridView", items="GridItemModel")
        def cmd(ctx, view, items):
            return view, items

        assert cmd(ctx) == (view, items)

    def test_fails_on_first_missing(self):
        ctx = _make_ctx(instances={"GridView": MagicMock()})

        @require(view="GridView", items="GridItemModel")
        def cmd(ctx, view, items):
            return (view, items)

        assert cmd(ctx) is None

    def test_preserves_extra_kwargs(self):
        sm = MagicMock()
        ctx = _make_ctx(instances={"SM": sm})

        @require(sm="SM")
        def cmd(ctx, sm, volume: int = 40):
            return sm, volume

        assert cmd(ctx, volume=80) == (sm, 80)

    def test_functools_wraps_preserves_name(self):
        @require(sm="SM")
        def my_command(ctx, sm):
            pass

        assert my_command.__name__ == "my_command"


class TestRequireV:
    def test_injects_value(self):
        ctx = _make_ctx(values={"path": "/a.mp4"})

        @require_v(path="path")
        def cmd(ctx, path):
            return path

        assert cmd(ctx) == "/a.mp4"

    def test_returns_none_when_falsy(self):
        ctx = _make_ctx(values={"path": None})

        @require_v(path="path")
        def cmd(ctx, path):
            return path

        assert cmd(ctx) is None

    def test_returns_none_for_empty_string(self):
        ctx = _make_ctx(values={"path": ""})

        @require_v(path="path")
        def cmd(ctx, path):
            return path

        assert cmd(ctx) is None

    def test_returns_none_for_empty_list(self):
        ctx = _make_ctx(values={"paths": []})

        @require_v(paths="paths")
        def cmd(ctx, paths):
            return paths

        assert cmd(ctx) is None

    def test_multiple_values(self):
        ctx = _make_ctx(values={"path": "/a.mp4", "name": "a"})

        @require_v(path="path", name="name")
        def cmd(ctx, path, name):
            return path, name

        assert cmd(ctx) == ("/a.mp4", "a")

    def test_functools_wraps_preserves_name(self):
        @require_v(path="path")
        def my_command(ctx, path):
            pass

        assert my_command.__name__ == "my_command"
