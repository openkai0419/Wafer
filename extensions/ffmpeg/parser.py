from __future__ import annotations
import json
import subprocess
from fractions import Fraction

from wafer.utils.logs import AppLogger


def _parse_frame_rate(rate_str: str) -> float | None:
    if not rate_str or rate_str == "0/0":
        return None
    try:
        return float(Fraction(rate_str))
    except (ValueError, ZeroDivisionError):
        return None


def _to_num(value: str) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def probe(path: str, ffprobe_path: str) -> dict | None:
    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception as e:
        AppLogger.debug(f"[ffmpeg] ffprobe failed for {path}: {e}")
        return None


def flatten(data: dict) -> tuple[dict[str, str], float | None]:
    meta: dict[str, str] = {}
    aspect: float | None = None

    fmt = data.get("format", {})
    if dur := fmt.get("duration"):
        meta["Duration"] = dur
    if br := fmt.get("bit_rate"):
        meta["Bitrate"] = br
    if fmt_name := fmt.get("format_name"):
        meta["FormatName"] = fmt_name
    if fmt_long := fmt.get("format_long_name"):
        meta["FormatLongName"] = fmt_long

    for key, val in fmt.get("tags", {}).items():
        if val and str(val).strip():
            meta[f"Tag/{key}"] = str(val).strip()

    video_found = False
    audio_found = False
    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type", "")

        if codec_type == "video" and not video_found:
            video_found = True
            if cn := stream.get("codec_name"):
                meta["VideoCodec"] = cn
            if cl := stream.get("codec_long_name"):
                meta["VideoCodecLong"] = cl
            w = stream.get("width")
            h = stream.get("height")
            if w and h:
                meta["Width"] = str(w)
                meta["Height"] = str(h)
                try:
                    aspect = int(w) / int(h)
                except (ValueError, ZeroDivisionError):
                    pass
            if pf := stream.get("pix_fmt"):
                meta["PixelFormat"] = pf
            fps = _parse_frame_rate(stream.get("r_frame_rate", ""))
            if fps:
                meta["FrameRate"] = f"{fps:.3f}"
            if vbr := stream.get("bit_rate"):
                meta["VideoBitrate"] = vbr
            for key, val in stream.get("tags", {}).items():
                if val and str(val).strip():
                    meta[f"VideoTag/{key}"] = str(val).strip()

        elif codec_type == "audio" and not audio_found:
            audio_found = True
            if cn := stream.get("codec_name"):
                meta["AudioCodec"] = cn
            if cl := stream.get("codec_long_name"):
                meta["AudioCodecLong"] = cl
            if sr := stream.get("sample_rate"):
                meta["SampleRate"] = sr
            if ch := stream.get("channels"):
                meta["Channels"] = str(ch)
            if abr := stream.get("bit_rate"):
                meta["AudioBitrate"] = abr
            for key, val in stream.get("tags", {}).items():
                if val and str(val).strip():
                    meta[f"AudioTag/{key}"] = str(val).strip()

    return meta, aspect
