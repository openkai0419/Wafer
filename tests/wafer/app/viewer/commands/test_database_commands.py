import py_compile


def test_compile():
    py_compile.compile('wafer/app/viewer/commands/database_commands.py')


def test_remove_database_uses_ipc():
    import ast
    with open('wafer/app/viewer/commands/database_commands.py') as f:
        source = f.read()
    assert 'deleteflag' not in source
    assert 'send_reliable' in source
