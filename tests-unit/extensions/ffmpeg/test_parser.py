import pytest
from extensions.ffmpeg.parser import flatten, _parse_frame_rate


SAMPLE_FFPROBE_OUTPUT = {
    "format": {
        "filename": "test.mp4",
        "nb_streams": 2,
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "format_long_name": "QuickTime / MOV",
        "duration": "12.345",
        "bit_rate": "5000000",
        "tags": {
            "encoder": "Lavf58.29.100",
            "creation_time": "2024-01-15T10:30:00.000000Z",
            "prompt": '[{"class_type":"CheckpointLoaderSimple"}]',
            "workflow": '{"nodes":{}}',
        },
    },
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "codec_long_name": "H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "r_frame_rate": "30/1",
            "bit_rate": "4500000",
            "tags": {"language": "und", "handler_name": "VideoHandler"},
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "codec_long_name": "AAC (Advanced Audio Coding)",
            "sample_rate": "44100",
            "channels": 2,
            "bit_rate": "128000",
            "tags": {"language": "eng"},
        },
    ],
}


class TestParseFrameRate:
    def test_simple_fraction(self):
        assert _parse_frame_rate("30/1") == 30.0

    def test_complex_fraction(self):
        result = _parse_frame_rate("30000/1001")
        assert abs(result - 29.97) < 0.01

    def test_zero_division(self):
        assert _parse_frame_rate("0/0") is None

    def test_empty_string(self):
        assert _parse_frame_rate("") is None

    def test_none(self):
        assert _parse_frame_rate(None) is None


class TestFlatten:
    def test_basic_metadata(self):
        meta, aspect = flatten(SAMPLE_FFPROBE_OUTPUT)
        assert meta["Duration"] == "12.345"
        assert meta["Bitrate"] == "5000000"
        assert meta["FormatName"] == "mov,mp4,m4a,3gp,3g2,mj2"

    def test_video_stream(self):
        meta, aspect = flatten(SAMPLE_FFPROBE_OUTPUT)
        assert meta["VideoCodec"] == "h264"
        assert meta["Width"] == "1920"
        assert meta["Height"] == "1080"
        assert meta["PixelFormat"] == "yuv420p"
        assert meta["FrameRate"] == "30.000"
        assert meta["VideoBitrate"] == "4500000"

    def test_audio_stream(self):
        meta, aspect = flatten(SAMPLE_FFPROBE_OUTPUT)
        assert meta["AudioCodec"] == "aac"
        assert meta["SampleRate"] == "44100"
        assert meta["Channels"] == "2"
        assert meta["AudioBitrate"] == "128000"

    def test_aspect_ratio(self):
        meta, aspect = flatten(SAMPLE_FFPROBE_OUTPUT)
        assert abs(aspect - (1920 / 1080)) < 0.001

    def test_container_tags(self):
        meta, aspect = flatten(SAMPLE_FFPROBE_OUTPUT)
        assert meta["Tag/encoder"] == "Lavf58.29.100"
        assert meta["Tag/creation_time"] == "2024-01-15T10:30:00.000000Z"

    def test_comfyui_metadata(self):
        meta, aspect = flatten(SAMPLE_FFPROBE_OUTPUT)
        assert "Tag/prompt" in meta
        assert "CheckpointLoaderSimple" in meta["Tag/prompt"]
        assert "Tag/workflow" in meta

    def test_stream_tags(self):
        meta, aspect = flatten(SAMPLE_FFPROBE_OUTPUT)
        assert meta["VideoTag/language"] == "und"
        assert meta["AudioTag/language"] == "eng"

    def test_empty_data(self):
        meta, aspect = flatten({})
        assert meta == {}
        assert aspect is None

    def test_audio_only(self):
        data = {
            "format": {"duration": "180.0", "bit_rate": "320000", "format_name": "mp3"},
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "mp3",
                    "sample_rate": "48000",
                    "channels": 2,
                }
            ],
        }
        meta, aspect = flatten(data)
        assert meta["AudioCodec"] == "mp3"
        assert meta["Duration"] == "180.0"
        assert "VideoCodec" not in meta
        assert aspect is None

    def test_multiple_video_streams_uses_first(self):
        data = {
            "format": {},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "30/1"},
                {"codec_type": "video", "codec_name": "mjpeg", "width": 320, "height": 240, "r_frame_rate": "0/0"},
            ],
        }
        meta, aspect = flatten(data)
        assert meta["VideoCodec"] == "h264"
        assert meta["Width"] == "1920"
