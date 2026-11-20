import os
from pathlib import Path

from PySide6 import QtCore, QtGui

from wafer.qt.transfer.dragparser import MimeDataParser, ParsedItem
from wafer.core.platform.file_operations import DropPlanItem, FileExecutor, PasteDecision
from wafer.core.common.virtual_paths import build_virtual_path


class _Saver:
    def save(self, item, target_path, move=False):
        src = Path(item.source) if item.is_local_file() else None
        dst = Path(target_path)
        plan = DropPlanItem(
            index=0,
            src=src,
            name=dst.name,
            is_dir=bool(src and src.is_dir()),
            action="cut" if move else "copy",
            dst_default=dst,
            conflict=dst.exists(),
            suggested_dst=None,
            parsed_item=item,
        )
        return FileExecutor(ask_conflict=lambda conflict: "overwrite").execute_one(plan, PasteDecision(mode="create"))


def test_mimedata_parser_parse_collects_all_local_urls(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")

    mime = QtCore.QMimeData()
    mime.setUrls(
        [
            QtCore.QUrl.fromLocalFile(str(a)),
            QtCore.QUrl.fromLocalFile(str(b)),
        ]
    )

    items = MimeDataParser().parse(mime)
    assert isinstance(items, list)
    assert len(items) == 2
    assert {os.path.basename(x.source) for x in items if isinstance(x, ParsedItem)} == {"a.txt", "b.txt"}


def test_mimedata_parser_prefers_local_urls_over_filegroupdescriptor(qtbot, tmp_path):
    from PySide6 import QtCore

    from wafer.core.common.paths import normalize_path
    from wafer.qt.transfer.dragparser import MimeDataParser

    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(src))])

    fmt = 'application/x-qt-windows-mime;value="FileGroupDescriptorW"'
    buf = bytearray(4 + 592)
    buf[0:4] = (1).to_bytes(4, "little")
    name = "b.txt".encode("utf-16le")
    buf[4 + 72 : 4 + 72 + len(name)] = name
    mime.setData(fmt, QtCore.QByteArray(bytes(buf)))

    items = MimeDataParser().parse(mime)
    assert len(items) == 1
    assert items[0].is_local_file() is True
    assert str(items[0].source) == normalize_path(str(src))


def test_mimedata_parser_ignores_invalid_filegroupdescriptor(monkeypatch):
    monkeypatch.setattr("wafer.qt.transfer.dragparser.platform.system", lambda: "Windows")
    mime = QtCore.QMimeData()
    fmt = 'application/x-qt-windows-mime;value="FileGroupDescriptorW"'
    mime.setData(fmt, QtCore.QByteArray())

    parser = MimeDataParser()

    assert parser.can_accept(mime) is True
    assert parser.parse(mime) == []


def _descriptor(names: list[str], *, wide: bool) -> bytes:
    record, codec = (592, "utf-16le") if wide else (332, "mbcs")
    buf = bytearray(4 + record * len(names))
    buf[0:4] = len(names).to_bytes(4, "little")
    for i, name in enumerate(names):
        encoded = name.encode(codec)
        start = 4 + i * record + 72
        buf[start : start + len(encoded)] = encoded
    return bytes(buf)


def test_filegroupdescriptor_reads_long_names_of_every_entry(monkeypatch):
    monkeypatch.setattr("wafer.qt.transfer.dragparser.platform.system", lambda: "Windows")
    long_name = "a" * 140 + ".png"
    mime = QtCore.QMimeData()
    mime.setData('application/x-qt-windows-mime;value="FileGroupDescriptorW"', QtCore.QByteArray(_descriptor([long_name, "b.png", "noext"], wide=True)))

    items = MimeDataParser().parse(mime)

    assert [item.name for item in items] == [long_name, "b.png", "noext"]


def test_filegroupdescriptor_ansi_records_are_332_bytes(monkeypatch):
    monkeypatch.setattr("wafer.qt.transfer.dragparser.platform.system", lambda: "Windows")
    mime = QtCore.QMimeData()
    mime.setData('application/x-qt-windows-mime;value="FileGroupDescriptor"', QtCore.QByteArray(_descriptor(["first.txt", "second.txt"], wide=False)))

    items = MimeDataParser().parse(mime)

    assert [item.name for item in items] == ["first.txt", "second.txt"]


def test_image_data_is_encoded_as_png(qtbot):
    image = QtGui.QImage(3, 2, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor(10, 20, 30))
    mime = QtCore.QMimeData()
    mime.setImageData(image)

    items = MimeDataParser().parse(mime)

    assert len(items) == 1
    assert items[0].name == "image.png"
    assert items[0].is_binary is True
    decoded = QtGui.QImage.fromData(items[0].source, "PNG")
    assert (decoded.width(), decoded.height()) == (3, 2)


def test_execute_one_copies_and_moves_files_and_dirs(tmp_path):
    saver = _Saver()

    src_file = tmp_path / "src.txt"
    src_file.write_text("x", encoding="utf-8")
    dst_file = tmp_path / "dst.txt"
    saver.save(ParsedItem(str(src_file), "src.txt"), str(dst_file), move=False)
    assert src_file.exists()
    assert dst_file.exists()
    assert dst_file.read_text(encoding="utf-8") == "x"

    src_file2 = tmp_path / "src2.txt"
    src_file2.write_text("y", encoding="utf-8")
    dst_file2 = tmp_path / "dst2.txt"
    saver.save(ParsedItem(str(src_file2), "src2.txt"), str(dst_file2), move=True)
    assert not src_file2.exists()
    assert dst_file2.exists()
    assert dst_file2.read_text(encoding="utf-8") == "y"

    src_dir = tmp_path / "src_dir"
    src_dir.mkdir()
    (src_dir / "inner.txt").write_text("z", encoding="utf-8")
    dst_dir = tmp_path / "dst_dir"
    saver.save(ParsedItem(str(src_dir), "src_dir"), str(dst_dir), move=False)
    assert src_dir.exists()
    assert (dst_dir / "inner.txt").exists()
    assert (dst_dir / "inner.txt").read_text(encoding="utf-8") == "z"

    src_dir2 = tmp_path / "src_dir2"
    src_dir2.mkdir()
    (src_dir2 / "inner2.txt").write_text("w", encoding="utf-8")
    dst_dir2 = tmp_path / "dst_dir2"
    saver.save(ParsedItem(str(src_dir2), "src_dir2"), str(dst_dir2), move=True)
    assert not src_dir2.exists()
    assert (dst_dir2 / "inner2.txt").exists()
    assert (dst_dir2 / "inner2.txt").read_text(encoding="utf-8") == "w"


def test_execute_one_skips_same_path(tmp_path):
    saver = _Saver()
    src_file = tmp_path / "same.txt"
    src_file.write_text("x", encoding="utf-8")
    saver.save(ParsedItem(str(src_file), "same.txt"), str(src_file), move=False)
    assert src_file.exists()
    assert src_file.read_text(encoding="utf-8") == "x"


def test_execute_one_skips_dir_into_itself(tmp_path):
    saver = _Saver()
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("x", encoding="utf-8")
    dst_inside = src_dir / "child"
    saver.save(ParsedItem(str(src_dir), "src"), str(dst_inside), move=False)
    assert (src_dir / "a.txt").exists()
    assert not dst_inside.exists()


def test_execute_one_rejects_virtual_remote_destination(tmp_path):
    saver = _Saver()
    virtual_dst = build_virtual_path(str(tmp_path / "archive.zip"), "remote.txt")

    result = saver.save(ParsedItem(b"x", "remote.txt", is_binary=True), virtual_dst)

    assert result.status == "skipped"
    assert result.error == "virtual path rejected"
