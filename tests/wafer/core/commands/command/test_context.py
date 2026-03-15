import pytest
from unittest.mock import MagicMock

from wafer.core.commands.command.context import (
    CommandContext,
    _wheel_steps_from_event,
    _global_pos_from_event,
    _local_pos_from_event,
    _pos_from_global,
)


class TestWheelStepsFromEvent:
    def test_none_event(self):
        assert _wheel_steps_from_event(None) is None

    def test_angle_delta_120_gives_1(self):
        ev = MagicMock()
        delta = MagicMock()
        delta.y.return_value = 120
        ev.angleDelta.return_value = delta
        assert _wheel_steps_from_event(ev) == 1

    def test_angle_delta_240_gives_2(self):
        ev = MagicMock()
        delta = MagicMock()
        delta.y.return_value = 240
        ev.angleDelta.return_value = delta
        assert _wheel_steps_from_event(ev) == 2

    def test_negative_angle_delta_gives_positive_steps(self):
        ev = MagicMock()
        delta = MagicMock()
        delta.y.return_value = -360
        ev.angleDelta.return_value = delta
        assert _wheel_steps_from_event(ev) == 3

    def test_zero_angle_falls_through_to_pixel(self):
        ev = MagicMock()
        delta_a = MagicMock()
        delta_a.y.return_value = 0
        ev.angleDelta.return_value = delta_a
        delta_p = MagicMock()
        delta_p.y.return_value = 200
        ev.pixelDelta.return_value = delta_p
        assert _wheel_steps_from_event(ev) == 2

    def test_no_delta_methods(self):
        ev = MagicMock(spec=[])
        assert _wheel_steps_from_event(ev) is None

    def test_angle_delta_small_value_gives_1(self):
        ev = MagicMock()
        delta = MagicMock()
        delta.y.return_value = 30
        ev.angleDelta.return_value = delta
        assert _wheel_steps_from_event(ev) == 1


class TestGlobalPosFromEvent:
    def test_none_event(self):
        assert _global_pos_from_event(None) is None

    def test_event_with_global_position_method(self):
        ev = MagicMock()
        pt = MagicMock()
        pt.toPoint.return_value = (100, 200)
        ev.globalPosition.return_value = pt
        assert _global_pos_from_event(ev) == (100, 200)

    def test_event_with_global_pos_method(self):
        ev = MagicMock(spec=["globalPos"])
        ev.globalPos.return_value = (50, 60)
        assert _global_pos_from_event(ev) == (50, 60)

    def test_event_without_any_method(self):
        ev = MagicMock(spec=[])
        assert _global_pos_from_event(ev) is None


class TestLocalPosFromEvent:
    def test_none_event(self):
        assert _local_pos_from_event(None) is None

    def test_event_with_position_method(self):
        ev = MagicMock()
        pt = MagicMock()
        pt.toPoint.return_value = (10, 20)
        ev.position.return_value = pt
        assert _local_pos_from_event(ev) == (10, 20)

    def test_event_with_pos_method(self):
        ev = MagicMock(spec=["pos"])
        ev.pos.return_value = (30, 40)
        assert _local_pos_from_event(ev) == (30, 40)

    def test_event_without_any_method(self):
        ev = MagicMock(spec=[])
        assert _local_pos_from_event(ev) is None


class TestPosFromGlobal:
    def test_none_widget(self):
        assert _pos_from_global(None, (10, 10)) is None

    def test_none_global_pos(self):
        assert _pos_from_global(MagicMock(), None) is None

    def test_widget_without_map_from_global(self):
        w = MagicMock(spec=[])
        assert _pos_from_global(w, (10, 10)) is None

    def test_widget_with_map_from_global(self):
        w = MagicMock()
        w.mapFromGlobal.return_value = (5, 5)
        assert _pos_from_global(w, (100, 100)) == (5, 5)


class TestCommandContextGet:
    def test_get_from_extras(self):
        ctx = CommandContext()
        ctx.extras["path"] = "/some/path"
        assert ctx.get("path") == "/some/path"

    def test_get_public_field(self):
        ctx = CommandContext()
        ctx.wheel_steps = 3
        assert ctx.get("wheel_steps") == 3

    def test_get_private_field_blocked(self):
        ctx = CommandContext()
        ctx._scope = "viewer"
        assert ctx.get("_scope") is None

    def test_get_widget_cache_blocked(self):
        ctx = CommandContext()
        assert ctx.get("_widget_cache") is None

    def test_get_default(self):
        ctx = CommandContext()
        assert ctx.get("missing", "fallback") == "fallback"

    def test_get_event(self):
        ev = MagicMock()
        ctx = CommandContext()
        ctx.event = ev
        assert ctx.get("event") is ev

    def test_get_event_method(self):
        ev = MagicMock()
        ctx = CommandContext()
        ctx.event = ev
        assert ctx.get_event() is ev

    def test_get_event_default(self):
        ctx = CommandContext()
        sentinel = object()
        assert ctx.get_event(sentinel) is sentinel

    def test_extras_take_priority_over_fields(self):
        ctx = CommandContext()
        ctx.wheel_steps = 5
        ctx.extras["wheel_steps"] = 99
        assert ctx.get("wheel_steps") == 99


class TestCommandContextGetMany:
    def test_empty_keys(self):
        ctx = CommandContext()
        assert ctx.get_many([]) == []

    def test_multiple_keys(self):
        ctx = CommandContext()
        ctx.extras["a"] = 1
        ctx.extras["b"] = 2
        assert ctx.get_many(["a", "b", "c"], default=0) == [1, 2, 0]


class TestCommandContextPut:
    def test_put_returns_self(self):
        ctx = CommandContext()
        result = ctx.put("key", "value")
        assert result is ctx

    def test_put_stores_value(self):
        ctx = CommandContext()
        ctx.put("key", "value")
        assert ctx.get("key") == "value"

    def test_put_overwrites(self):
        ctx = CommandContext()
        ctx.put("key", "v1")
        ctx.put("key", "v2")
        assert ctx.get("key") == "v2"


class TestCommandContextPutDefault:
    def test_put_default_sets_when_missing(self):
        ctx = CommandContext()
        ctx.put_default("key", "default_val")
        assert ctx.get("key") == "default_val"

    def test_put_default_does_not_overwrite(self):
        ctx = CommandContext()
        ctx.put("key", "original")
        ctx.put_default("key", "default_val")
        assert ctx.get("key") == "original"

    def test_put_default_returns_self(self):
        ctx = CommandContext()
        result = ctx.put_default("key", "val")
        assert result is ctx


class TestCommandContextMerge:
    def test_merge_adds_extras(self):
        ctx = CommandContext()
        ctx.merge({"a": 1, "b": 2})
        assert ctx.get("a") == 1
        assert ctx.get("b") == 2

    def test_merge_overwrites_existing(self):
        ctx = CommandContext()
        ctx.put("a", "old")
        ctx.merge({"a": "new"})
        assert ctx.get("a") == "new"

    def test_merge_none_is_noop(self):
        ctx = CommandContext()
        ctx.put("a", 1)
        result = ctx.merge(None)
        assert result is ctx
        assert ctx.get("a") == 1

    def test_merge_empty_dict_is_noop(self):
        ctx = CommandContext()
        ctx.put("a", 1)
        ctx.merge({})
        assert ctx.get("a") == 1

    def test_merge_returns_self(self):
        ctx = CommandContext()
        result = ctx.merge({"x": 1})
        assert result is ctx


class TestCommandContextBuild:
    def test_build_stores_widget_scope_source(self):
        w = MagicMock()
        ctx = CommandContext.build(w, "GridView", source="keyboard")
        assert ctx._widget is w
        assert ctx._scope == "GridView"
        assert ctx._source == "keyboard"

    def test_build_defaults_scope_to_star(self):
        ctx = CommandContext.build()
        assert ctx._scope == "*"

    def test_build_defaults_source_to_empty(self):
        ctx = CommandContext.build()
        assert ctx._source == ""

    def test_build_none_scope_becomes_star(self):
        ctx = CommandContext.build(scope=None)
        assert ctx._scope == "*"

    def test_build_with_extras(self):
        ctx = CommandContext.build(extras={"foo": "bar"})
        assert ctx.get("foo") == "bar"

    def test_build_with_none_extras(self):
        ctx = CommandContext.build(extras=None)
        assert ctx.extras == {}

    def test_build_wheel_steps_defaults_to_1(self):
        ctx = CommandContext.build()
        assert ctx.wheel_steps == 1


class TestCommandContextCreate:
    def test_create_infers_scope_from_widget(self):
        w = MagicMock()
        w.binding_scope.return_value = "ImageView"
        ctx = CommandContext.create(w)
        assert ctx._scope == "ImageView"

    def test_create_falls_back_to_star_when_no_binding_scope(self):
        w = MagicMock(spec=[])
        ctx = CommandContext.create(w)
        assert ctx._scope == "*"

    def test_create_explicit_scope_overrides_widget(self):
        w = MagicMock()
        w.binding_scope.return_value = "ImageView"
        ctx = CommandContext.create(w, scope="Override")
        assert ctx._scope == "Override"

    def test_create_merges_seed(self):
        seed = CommandContext()
        seed._scope = "viewer"
        seed.extras["seed_key"] = "seed_val"
        ctx = CommandContext.create(extras={"ctx_key": "ctx_val"}, seed=seed)
        assert ctx._scope == "viewer"
        assert ctx.get("seed_key") == "seed_val"
        assert ctx.get("ctx_key") == "ctx_val"

    def test_create_binding_scope_exception_falls_back_to_star(self):
        w = MagicMock()
        w.binding_scope.side_effect = RuntimeError("broken")
        ctx = CommandContext.create(w)
        assert ctx._scope == "*"


class TestMergeSeedEdgeCases:
    def test_merge_seed_none_is_noop(self):
        ctx = CommandContext()
        ctx.pos = (1, 2)
        result = CommandContext.merge_seed(ctx, None)
        assert result is ctx
        assert ctx.pos == (1, 2)

    def test_merge_seed_prefers_seed_scope_over_star(self):
        ctx = CommandContext()
        ctx._scope = "*"
        seed = CommandContext()
        seed._scope = "grid"
        CommandContext.merge_seed_prefer_ctx(ctx, seed)
        assert ctx._scope == "grid"

    def test_merge_seed_prefer_ctx_keeps_nonstar_scope(self):
        ctx = CommandContext()
        ctx._scope = "viewer"
        seed = CommandContext()
        seed._scope = "grid"
        CommandContext.merge_seed_prefer_ctx(ctx, seed)
        assert ctx._scope == "viewer"

    def test_merge_seed_prefer_seed_overwrites_pos(self):
        ctx = CommandContext()
        ctx.pos = (1, 1)
        seed = CommandContext()
        seed.pos = (10, 10)
        CommandContext.merge_seed_prefer_seed(ctx, seed)
        assert ctx.pos == (10, 10)

    def test_merge_seed_prefer_ctx_keeps_pos_when_set(self):
        ctx = CommandContext()
        ctx.pos = (1, 1)
        seed = CommandContext()
        seed.pos = (10, 10)
        CommandContext.merge_seed_prefer_ctx(ctx, seed)
        assert ctx.pos == (1, 1)

    def test_merge_seed_prefer_ctx_takes_seed_pos_when_none(self):
        ctx = CommandContext()
        ctx.pos = None
        seed = CommandContext()
        seed.pos = (10, 10)
        CommandContext.merge_seed_prefer_ctx(ctx, seed)
        assert ctx.pos == (10, 10)


class TestCommandContextDebug:
    def test_to_debug_dict_keys(self):
        ctx = CommandContext.build()
        d = ctx.to_debug_dict()
        assert "info" in d
        assert "pos" in d
        assert "global_pos" in d
        assert "extras" in d

    def test_to_debug_text_returns_string(self):
        ctx = CommandContext.build()
        assert isinstance(ctx.to_debug_text(), str)

    def test_print_debug_calls_printer(self):
        ctx = CommandContext.build()
        called = []
        ctx.print_debug(printer=lambda msg: called.append(msg))
        assert len(called) == 1
