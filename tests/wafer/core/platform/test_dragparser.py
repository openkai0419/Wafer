import os
import py_compile
from PySide6 import QtCore

from wafer.core.platform.dragparser import MimeDataParser, ParsedItem
from wafer.core.platform.file_operations import FileSaver


def test_compile():
    py_compile.compile('wafer/core/platform/dragparser.py')


def test_mimedata_parser_parse_collects_all_local_urls(tmp_path):
    a = tmp_path / 'a.txt'
    b = tmp_path / 'b.txt'
    a.write_text('a', encoding='utf-8')
    b.write_text('b', encoding='utf-8')

    mime = QtCore.QMimeData()
    mime.setUrls([
        QtCore.QUrl.fromLocalFile(str(a)),
        QtCore.QUrl.fromLocalFile(str(b)),
    ])

    items = MimeDataParser().parse(mime)
    assert isinstance(items, list)
    assert len(items) == 2
    assert {os.path.basename(x.source) for x in items if isinstance(x, ParsedItem)} == {'a.txt', 'b.txt'}


def test_mimedata_parser_prefers_local_urls_over_filegroupdescriptor(qtbot, tmp_path):
    from PySide6 import QtCore

    from wafer.utils.paths import normalize_path
    from wafer.core.platform.dragparser import MimeDataParser

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


def test_file_saver_copies_and_moves_files_and_dirs(tmp_path):
    saver = FileSaver()

    src_file = tmp_path / 'src.txt'
    src_file.write_text('x', encoding='utf-8')
    dst_file = tmp_path / 'dst.txt'
    saver.save(ParsedItem(str(src_file), 'src.txt'), str(dst_file), move=False)
    assert src_file.exists()
    assert dst_file.exists()
    assert dst_file.read_text(encoding='utf-8') == 'x'

    src_file2 = tmp_path / 'src2.txt'
    src_file2.write_text('y', encoding='utf-8')
    dst_file2 = tmp_path / 'dst2.txt'
    saver.save(ParsedItem(str(src_file2), 'src2.txt'), str(dst_file2), move=True)
    assert not src_file2.exists()
    assert dst_file2.exists()
    assert dst_file2.read_text(encoding='utf-8') == 'y'

    src_dir = tmp_path / 'src_dir'
    src_dir.mkdir()
    (src_dir / 'inner.txt').write_text('z', encoding='utf-8')
    dst_dir = tmp_path / 'dst_dir'
    saver.save(ParsedItem(str(src_dir), 'src_dir'), str(dst_dir), move=False)
    assert src_dir.exists()
    assert (dst_dir / 'inner.txt').exists()
    assert (dst_dir / 'inner.txt').read_text(encoding='utf-8') == 'z'

    src_dir2 = tmp_path / 'src_dir2'
    src_dir2.mkdir()
    (src_dir2 / 'inner2.txt').write_text('w', encoding='utf-8')
    dst_dir2 = tmp_path / 'dst_dir2'
    saver.save(ParsedItem(str(src_dir2), 'src_dir2'), str(dst_dir2), move=True)
    assert not src_dir2.exists()
    assert (dst_dir2 / 'inner2.txt').exists()
    assert (dst_dir2 / 'inner2.txt').read_text(encoding='utf-8') == 'w'


def test_file_saver_skips_same_path(tmp_path):
    saver = FileSaver()
    src_file = tmp_path / 'same.txt'
    src_file.write_text('x', encoding='utf-8')
    saver.save(ParsedItem(str(src_file), 'same.txt'), str(src_file), move=False)
    assert src_file.exists()
    assert src_file.read_text(encoding='utf-8') == 'x'


def test_file_saver_skips_dir_into_itself(tmp_path):
    saver = FileSaver()
    src_dir = tmp_path / 'src'
    src_dir.mkdir()
    (src_dir / 'a.txt').write_text('x', encoding='utf-8')
    dst_inside = src_dir / 'child'
    saver.save(ParsedItem(str(src_dir), 'src'), str(dst_inside), move=False)
    assert (src_dir / 'a.txt').exists()
    assert not dst_inside.exists()
