from wafer.web.media import NATIVE_VIDEO_EXTS, VIDEO_EXTS, classify


def test_classify_image():
    assert classify("a.png") == "image"
    assert classify("a.JPG") == "image"
    assert classify("dir/sub/b.webp") == "image"


def test_classify_native_video():
    assert classify("clip.mp4") == "video"
    assert classify("clip.WEBM") == "video"


def test_classify_unsupported_video():
    assert classify("clip.mkv") == "video-unsupported"
    assert classify("clip.avi") == "video-unsupported"


def test_classify_other():
    assert classify("notes.txt") == "other"
    assert classify("noext") == "other"


def test_native_video_is_subset_of_video():
    assert NATIVE_VIDEO_EXTS <= VIDEO_EXTS
