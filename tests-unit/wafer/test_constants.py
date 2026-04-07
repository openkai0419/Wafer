import py_compile


def test_compile():
    py_compile.compile("wafer/constants.py")


def test_virtual_path_separator_constant():
    from wafer.constants import VIRTUAL_PATH_SEPARATOR

    assert VIRTUAL_PATH_SEPARATOR == "::"
