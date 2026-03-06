import py_compile


def test_compile_types():
    py_compile.compile('wayfer/core/actions/binding/mouse/types.py')


def test_compile_drag():
    py_compile.compile('wayfer/core/actions/binding/mouse/drag.py')


def test_compile_manager():
    py_compile.compile('wayfer/core/actions/binding/mouse/manager.py')
