import py_compile


def test_compile():
    py_compile.compile('source/constants.py')


def test_virtual_path_separator_constant():
    from source.constants import VIRTUAL_PATH_SEPARATOR
    assert VIRTUAL_PATH_SEPARATOR == '::'
