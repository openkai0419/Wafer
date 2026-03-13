from wafer.plugin import MenuGroup, CommandMeta, CommandParam, require
from wafer.core.actions.bridge import Command


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
def set_volume(ctx, vw, volume: int = 100):
    vw.set_volume(int(volume))


@require(vw="VideoViewerWidget")
def toggle_mute(ctx, vw):
    vw.toggle_mute()


@require(vw="VideoViewerWidget")
def toggle_fit_mode(ctx, vw):
    vw.toggle_fit_mode()


@require(vw="VideoViewerWidget")
def set_speed(ctx, vw, speed: float = 1.0):
    vw.set_speed(float(speed))


@require(vw="VideoViewerWidget")
def toggle_loop(ctx, vw):
    vw.toggle_loop()


class VideoViewerCommands(MenuGroup):
    NAME = "Video Viewer"
    PRIORITY = 1100

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
                path="vview.set_volume",
                display="Volume",
                func=set_volume,
                params=[CommandParam(name="volume", value=50, min_value=0, max_value=100)],
            ),
            CommandMeta(
                path="vview.toggle_mute",
                display="Mute",
                func=toggle_mute,
                checkable=True,
            ),
            "-",
            CommandMeta(
                path="vview.toggle_fit_mode",
                display="Contain/Cover",
                func=toggle_fit_mode,
                checkable=True,
            ),
            CommandMeta(
                path="vview.set_speed",
                display="Playback Speed",
                func=set_speed,
                params=[CommandParam(name="speed", value=1.0)],
            ),
            CommandMeta(
                path="vview.toggle_loop",
                display="Loop",
                func=toggle_loop,
                checkable=True,
            ),
        ]
