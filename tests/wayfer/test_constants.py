import py_compile


def test_compile():
    py_compile.compile('wayfer/constants.py')


def test_virtual_path_separator_constant():
    from wayfer.constants import VIRTUAL_PATH_SEPARATOR
    assert VIRTUAL_PATH_SEPARATOR == '::'
