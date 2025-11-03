import py_compile


def test_compile():
    py_compile.compile('source/actions/actionbase.py')
    py_compile.compile('source/actions/commandbase.py')
    py_compile.compile('source/actions/context_menu.py')
    py_compile.compile('source/actions/file_commands.py')
