import io

from PIL import Image

from wafer.web import media


def test_build_thumbnail_downsizes_and_writes_webp(monkeypatch, tmp_path):
    from wafer.plugin.imageloader.handler import image_loader_resolver

    monkeypatch.setattr(image_loader_resolver, "load_pil", lambda path, size: Image.new("RGB", (300, 200)))
    out = tmp_path / "thumb.webp"
    assert media.build_thumbnail("whatever.png", 64, str(out)) is True
    img = Image.open(io.BytesIO(out.read_bytes()))
    assert img.format == "WEBP"
    assert max(img.size) <= 64


def test_build_thumbnail_returns_false_when_undecodable(monkeypatch, tmp_path):
    from wafer.plugin.imageloader.handler import image_loader_resolver

    monkeypatch.setattr(image_loader_resolver, "load_pil", lambda path, size: None)
    out = tmp_path / "thumb.webp"
    assert media.build_thumbnail("whatever.raw", 64, str(out)) is False
    assert not out.exists()


def test_thumb_cache_dir_is_web_scoped():
    assert "web_thumbs" in media.thumb_cache_dir()


def test_thumb_cache_singleton_rebinds_on_dir_change(monkeypatch, tmp_path):
    monkeypatch.setattr(media, "_thumb_cache", None)
    monkeypatch.setattr(media, "_thumb_cache_dir", None)

    a = tmp_path / "a"
    monkeypatch.setattr(media, "thumb_cache_dir", lambda: str(a))
    first = media.thumb_cache()
    assert media.thumb_cache() is first

    b = tmp_path / "b"
    monkeypatch.setattr(media, "thumb_cache_dir", lambda: str(b))
    assert media.thumb_cache() is not first
