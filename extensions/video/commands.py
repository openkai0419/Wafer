from wafer.plugin import MenuGroup, CommandMeta, CommandParam, require, require_v
from wafer.core.commands.binding.instance_registry import InstanceRegistry


def _sm():
    return InstanceRegistry.instance().get_one("VideoSlotManager")


@require(sm="VideoSlotManager")
def volume_up(ctx, sm, step: int = 5):
    sm.set_volume(sm.volume + int(step))


@require(sm="VideoSlotManager")
def volume_down(ctx, sm, step: int = 5):
    sm.set_volume(sm.volume - int(step))


@require(sm="VideoSlotManager")
def set_max_playback_slots(ctx, sm, max_slots: int = 3):
    sm.set_max_selected(int(max_slots))


@require(sm="VideoSlotManager")
def toggle_hover_autoplay(ctx, sm):
    sm.hover_autoplay = not sm.hover_autoplay
    if not sm.hover_autoplay:
        sm.deactivate_hover()


@require(sm="VideoSlotManager")
def toggle_appear_autoplay(ctx, sm):
    sm.appear_autoplay = not sm.appear_autoplay


@require(sm="VideoSlotManager")
def toggle_select_autoplay(ctx, sm):
    sm.select_autoplay = not sm.select_autoplay


@require(sm="VideoSlotManager")
def toggle_pause_in_background(ctx, sm):
    sm.pause_in_background = not sm.pause_in_background


class VideoGridCommands(MenuGroup):
    NAME = "Video"
    PRIORITY = 1000
    DEFAULT_ENABLED = True

    @classmethod
    def commands(cls):
        return [
            ":Video Grid",
            CommandMeta(
                path="vgrid.volume_up",
                display="Preview Volume Up",
                func=volume_up,
                params=[CommandParam(name="step", value=5, min_value=1, max_value=50)],
            ),
            CommandMeta(
                path="vgrid.volume_down",
                display="Preview Volume Down",
                func=volume_down,
                params=[CommandParam(name="step", value=5, min_value=1, max_value=50)],
            ),
            CommandMeta(
                path="vgrid.set_max_playback_slots",
                display="Max Playback Slots",
                func=set_max_playback_slots,
                params=[CommandParam(name="max_slots", value=3, min_value=1, max_value=50)],
            ),
            "-",
            ":Autoplay",
            CommandMeta(
                path="vgrid.toggle_select_autoplay",
                display="Autoplay on Select",
                func=toggle_select_autoplay,
                checked=lambda: getattr(_sm(), "select_autoplay", True),
            ),
            CommandMeta(
                path="vgrid.toggle_hover_autoplay",
                display="Autoplay on Hover",
                func=toggle_hover_autoplay,
                checked=lambda: getattr(_sm(), "hover_autoplay", True),
            ),
            CommandMeta(
                path="vgrid.toggle_appear_autoplay",
                display="Autoplay on Appear",
                func=toggle_appear_autoplay,
                checked=lambda: getattr(_sm(), "appear_autoplay", False),
            ),
            "-",
            CommandMeta(
                path="vgrid.toggle_pause_in_background",
                display="Pause in Background",
                func=toggle_pause_in_background,
                checked=lambda: getattr(_sm(), "pause_in_background", False),
            ),
        ]
