import ast
import sys
from pathlib import Path


def extract_from_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text('utf-8'), filename=str(path))
    except SyntaxError:
        return []
    packages = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ''
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name != 'install_packages':
            continue
        for arg in node.args:
            if isinstance(arg, ast.List):
                for elt in arg.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        packages.append(elt.value)
    return packages


def main():
    extensions_dir = Path(__file__).resolve().parent.parent / 'extensions'
    skip = {'.packages', '__pycache__', 'lib'}
    all_packages = []
    for py_file in extensions_dir.rglob('*.py'):
        if skip & set(py_file.parts):
            continue
        all_packages.extend(extract_from_file(py_file))

    unique = sorted(set(all_packages))
    if not unique:
        sys.exit(0)
    out = Path(__file__).resolve().parent.parent / '.temp' / 'dynamic_deps.txt'
    out.parent.mkdir(exist_ok=True)
    out.write_text('\n'.join(unique) + '\n', encoding='utf-8')
    print(str(out))


if __name__ == '__main__':
    main()
