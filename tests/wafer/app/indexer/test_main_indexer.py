import py_compile


def test_compile():
    py_compile.compile('wafer/app/indexer/main_indexer.py')


def test_compile_collector_receiver():
    py_compile.compile('wafer/app/indexer/collector_receiver.py')


def test_compile_scanner():
    py_compile.compile('wafer/app/indexer/scanner.py')
