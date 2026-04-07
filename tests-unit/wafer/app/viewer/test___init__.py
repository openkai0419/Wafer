import py_compile


def test_compile():
    py_compile.compile("wafer/app/viewer/__init__.py")
