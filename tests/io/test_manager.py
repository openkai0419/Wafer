import py_compile
import sys

import pytest
from PIL import Image

from source.io.manager import LoaderClass, ReaderClass, pil_to_qimage


def test_compile():
    py_compile.compile('source/io/manager.py')


def test_pil_to_qimage_rgb():
    img = Image.new('RGB', (10, 20), color='red')
    qimg = pil_to_qimage(img)
    assert qimg.width() == 10
    assert qimg.height() == 20
    assert not qimg.isNull()


def test_pil_to_qimage_rgba():
    img = Image.new('RGBA', (5, 5), color=(255, 0, 0, 128))
    qimg = pil_to_qimage(img)
    assert qimg.width() == 5
    assert qimg.height() == 5


def test_loader_class_has_thumbnailer_fallback():
    assert hasattr(LoaderClass, '_load_thumbnail')
    assert hasattr(LoaderClass, '_get_thumbnailer')


@pytest.mark.skipif(not sys.platform.startswith('win'), reason='Windows only')
def test_loader_thumbnail_fallback_for_nonimage(tmp_path):
    txt = tmp_path / 'hello.txt'
    txt.write_text('hello world')
    from PySide6 import QtCore
    size = QtCore.QSize(64, 64)
    result = LoaderClass.load(str(txt), size)
    # result could be None if OS can't generate thumbnail for txt
    # just ensure it doesn't crash
    assert result is None or not result.isNull()
