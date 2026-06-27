from wafer.plugin import MenuGroup, CommandMeta, CommandParam, require
from wafer.core.commands.binding.instance_registry import InstanceRegistry


def _vw():
    return InstanceRegistry.instance().get_one("VideoViewerWidget")


@require(vw="VideoViewerWidget")
def toggle_pause(ctx, vw):
    vw.toggle_pause()


@require(vw="VideoViewerWidget")
def seek_forward(ctx, vw, seconds: int = 10):
    vw.seek(int(seconds))


@require(vw="VideoViewerWidget")
def seek_backward(ctx, vw, seconds: int = 10):
    vw.seek(-int(seconds))


@require(vw="VideoViewerWidget")
def frame_step(ctx, vw):
    vw.frame_step()


@require(vw="VideoViewerWidget")
def frame_back_step(ctx, vw):
    vw.frame_back_step()


@require(vw="VideoViewerWidget")
def volume_up(ctx, vw, step: int = 5):
    vw.set_volume(vw._volume + int(step))


@require(vw="VideoViewerWidget")
def volume_down(ctx, vw, step: int = 5):
    vw.set_volume(vw._volume - int(step))


@require(vw="VideoViewerWidget")
def toggle_mute(ctx, vw):
    vw.toggle_mute()


@require(vw="VideoViewerWidget")
def toggle_fit_mode(ctx, vw):
    vw.toggle_fit_mode()


@require(vw="VideoViewerWidget")
def speed_up(ctx, vw, step: float = 0.25):
    vw.set_speed(vw._speed + float(step))


@require(vw="VideoViewerWidget")
def speed_down(ctx, vw, step: float = 0.25):
    vw.set_speed(vw._speed - float(step))


@require(vw="VideoViewerWidget")
def set_speed(ctx, vw, speed: float = 1.0):
    vw.set_speed(float(speed))


@require(vw="VideoViewerWidget")
def toggle_loop(ctx, vw):
    vw.toggle_loop()


@require(vw="VideoViewerWidget")
def toggle_pause_in_background(ctx, vw):
    vw.toggle_pause_in_background()


class VideoViewerCommands(MenuGroup):
    NAME = "Video"
    PRIORITY = 1100
    DEFAULT_ENABLED = True

    @classmethod
    def commands(cls):
        return [
            ":Video Viewer",
            CommandMeta(
                path="vview.toggle_pause",
                display="Play/Pause",
                func=toggle_pause,
            ),
            CommandMeta(
                path="vview.seek_forward",
                display="Seek Forward",
                func=seek_forward,
                params=[CommandParam(name="seconds", value=10)],
            ),
            CommandMeta(
                path="vview.seek_backward",
                display="Seek Backward",
                func=seek_backward,
                params=[CommandParam(name="seconds", value=10)],
            ),
            "-",
            CommandMeta(
                path="vview.frame_step",
                display="Next Frame",
                func=frame_step,
            ),
            CommandMeta(
                path="vview.frame_back_step",
                display="Previous Frame",
                func=frame_back_step,
            ),
            "-",
            CommandMeta(
                path="vview.volume_up",
                display="Volume Up",
                func=volume_up,
                params=[CommandParam(name="step", value=5, min_value=1, max_value=50)],
            ),
            CommandMeta(
                path="vview.volume_down",
                display="Volume Down",
                func=volume_down,
                params=[CommandParam(name="step", value=5, min_value=1, max_value=50)],
            ),
            CommandMeta(
                path="vview.toggle_mute",
                display="Mute",
                func=toggle_mute,
                checked=lambda: getattr(_vw(), "muted", False),
            ),
            "-",
            CommandMeta(
                path="vview.toggle_fit_mode",
                display="Contain/Cover",
                func=toggle_fit_mode,
                checked=lambda: getattr(_vw(), "cover_mode", False),
            ),
            CommandMeta(
                path="vview.speed_up",
                display="Speed Up",
                func=speed_up,
                params=[CommandParam(name="step", value=0.25)],
            ),
            CommandMeta(
                path="vview.speed_down",
                display="Speed Down",
                func=speed_down,
                params=[CommandParam(name="step", value=0.25)],
            ),
            CommandMeta(
                path="vview.set_speed",
                display="Set Speed",
                func=set_speed,
                params=[CommandParam(name="speed", value=1.0)],
            ),
            CommandMeta(
                path="vview.toggle_loop",
                display="Loop",
                func=toggle_loop,
                checked=lambda: getattr(_vw(), "looping", False),
            ),
            "-",
            CommandMeta(
                path="vview.toggle_pause_in_background",
                display="Pause in Background",
                func=toggle_pause_in_background,
                checked=lambda: getattr(_vw(), "pause_in_background", False),
            ),
        ]
