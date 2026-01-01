import ast
from pathlib import Path


def _iter_py_files() -> list[Path]:
    root = Path('source/actions')
    out: list[Path] = []
    for p in root.rglob('*.py'):
        if '__pycache__' in p.parts:
            continue
        if p.name in ('facade.py', '__init__.py'):
            continue
        out.append(p)
    return out


def _is_forbidden_facade_import(module: str | None, level: int, name: str | None) -> bool:
    if module is None:
        return False
    if module == 'source.actions.facade':
        return True
    if module.endswith('.facade') and level >= 1:
        return True
    return False


def test_actions_internal_must_not_import_facade():
    offenders: list[str] = []
    for p in _iter_py_files():
        tree = ast.parse(p.read_text(encoding='utf-8'))
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for alias in n.names:
                    if alias.name == 'source.actions.facade':
                        offenders.append(str(p))
            elif isinstance(n, ast.ImportFrom):
                if _is_forbidden_facade_import(n.module, n.level, None):
                    offenders.append(str(p))
    offenders = sorted(set(offenders))
    assert not offenders, 'facade.py must not be imported from inside source/actions: ' + ', '.join(offenders)
