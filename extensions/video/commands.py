from wafer.plugin import MenuGroup, CommandMeta, CommandParam, require, require_v
from wafer.core.actions.bridge import Command


@require(sm="VideoSlotManager")
def set_volume(ctx, sm, volume: int = 40):
    sm.set_volume(volume)


@require(sm="VideoSlotManager")
def set_max_playback_slots(ctx, sm, max_slots: int = 3):
    sm.set_max_selected(int(max_slots))


@require(sm="VideoSlotManager")
def toggle_hover_autoplay(ctx, sm):
    sm.hover_autoplay = not sm.hover_autoplay
    Command.set_checked("vgrid.toggle_hover_autoplay", sm.hover_autoplay)
    if not sm.hover_autoplay:
        sm.deactivate_hover()


@require(sm="VideoSlotManager")
def toggle_appear_autoplay(ctx, sm):
    sm.appear_autoplay = not sm.appear_autoplay
    Command.set_checked("vgrid.toggle_appear_autoplay", sm.appear_autoplay)


class VideoGridCommands(MenuGroup):
    NAME = "Video Grid"
    PRIORITY = 1000

    @classmethod
    def commands(cls):
        return [
            ":Video Grid",
            CommandMeta(
                path="vgrid.set_volume",
                display="Preview Volume",
                func=set_volume,
                params=[CommandParam(name="volume", value=40, min_value=0, max_value=100)],
            ),
            CommandMeta(
                path="vgrid.set_max_playback_slots",
                display="Max Playback Slots",
                func=set_max_playback_slots,
                params=[CommandParam(name="max_slots", value=3, min_value=1, max_value=10)],
            ),
            "-",
            ":Autoplay",
            CommandMeta(
                path="vgrid.toggle_hover_autoplay",
                display="Autoplay on Hover",
                func=toggle_hover_autoplay,
                checkable=True,
                default_checked=True,
            ),
            CommandMeta(
                path="vgrid.toggle_appear_autoplay",
                display="Autoplay on Appear",
                func=toggle_appear_autoplay,
                checkable=True,
                default_checked=False,
            ),
        ]
