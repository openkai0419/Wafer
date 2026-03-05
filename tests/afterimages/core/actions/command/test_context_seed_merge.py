from PySide6 import QtCore

from afterimages.core.actions.command.context import CommandContext


def test_merge_seed_prefer_seed_overrides_fields():
    seed = CommandContext()
    seed.pos = QtCore.QPoint(10, 10)
    seed.global_pos = QtCore.QPoint(11, 11)
    seed.start_pos = QtCore.QPoint(12, 12)
    seed.start_global_pos = QtCore.QPoint(13, 13)
    seed.wheel_steps = 3
    seed._scope = "viewer"
    seed.extras.update({"k": "seed", "only_seed": 1})

    ctx = CommandContext()
    ctx.pos = QtCore.QPoint(1, 1)
    ctx.global_pos = QtCore.QPoint(2, 2)
    ctx.start_pos = QtCore.QPoint(3, 3)
    ctx.start_global_pos = QtCore.QPoint(4, 4)
    ctx.wheel_steps = 1
    ctx._scope = "*"
    ctx.extras.update({"k": "ctx", "only_ctx": 2})

    CommandContext.merge_seed_prefer_seed(ctx, seed)

    assert ctx.pos == seed.pos
    assert ctx.global_pos == seed.global_pos
    assert ctx.start_pos == seed.start_pos
    assert ctx.start_global_pos == seed.start_global_pos
    assert ctx.wheel_steps == 3
    assert ctx._scope == "viewer"
    assert ctx.get("k") == "seed"
    assert ctx.get("only_seed") == 1
    assert ctx.get("only_ctx") == 2


def test_merge_seed_prefer_ctx_keeps_existing_fields():
    seed = CommandContext()
    seed.pos = QtCore.QPoint(10, 10)
    seed.extras.update({"k": "seed"})

    ctx = CommandContext()
    ctx.pos = QtCore.QPoint(1, 1)
    ctx.extras.update({"k": "ctx"})

    CommandContext.merge_seed_prefer_ctx(ctx, seed)

    assert ctx.pos == QtCore.QPoint(1, 1)
    assert ctx.get("k") == "ctx"
