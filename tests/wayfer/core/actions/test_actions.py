import py_compile
from pathlib import Path


def test_compile():
    root = Path('wayfer/core/actions')
    for p in root.rglob('*.py'):
        if '__pycache__' in p.parts:
            continue
        py_compile.compile(str(p), doraise=True)
