from scripts import memory_report


def test_role_of_cmdline():
    python = r"C:\app\.venv\Scripts\python.exe"
    main = r"C:\app\main.py"
    assert memory_report.role_of([python, main, "--collector", "db", "--plugin", "x"]) == "collector"
    assert memory_report.role_of([python, main, "--parser", "db", "--plugin", "x"]) == "parser"
    assert memory_report.role_of([python, main, "--indexer", "db"]) == "indexer"
    assert memory_report.role_of([python, main, "--viewer", "--slot", "s"]) == "viewer"
    assert memory_report.role_of([python, main, "--tray"]) == "tray"
    assert memory_report.role_of([python, main, "--webui"]) == "webui"
    assert memory_report.role_of([python, main]) == "root-viewer"


def test_other_python_processes_are_ignored():
    python = r"C:\app\.venv\Scripts\python.exe"
    assert memory_report.role_of([python, "-m", "pytest"]) is None
    assert memory_report.role_of([python, "other.py", "--viewer"]) is None
    assert memory_report.role_of([]) is None
    assert memory_report.role_of(["notepad.exe"]) is None
