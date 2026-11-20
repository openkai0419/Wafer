import pytest

from wafer.builtins.updater.plan import (
    PlanError,
    generate_plan,
    read_plan,
    validate_plan_relpath,
    write_plan,
)


def write_tree(root, spec: dict):
    for rel, content in spec.items():
        path = root / rel
        if content is None:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


OLD_TREE = {
    "python/wafer-pythonw.exe": "old-python",
    "python/Lib/site.py": "old-site",
    "main.py": "old-main",
    "Wafer.exe": "old-launcher",
    "Uninstaller.exe": "old-uninstaller",
    "wafer/_version.py": 'FALLBACK_VERSION = "1.0.0"\n',
    "_resources/translations.json": "old-res",
    "README.md": "old-readme",
    "extensions/image/__init__.py": "old-image",
    "extensions/ffmpeg/__init__.py": "old-ffmpeg",
    "extensions/ffmpeg/lib/ffmpeg.exe": "ffmpeg-bin",
    "extensions/color/__init__.py": "old-color",
    "extensions/myext/__init__.py": "user-ext",
    "extensions/.packages/numpy/__init__.py": "site-package",
    "extensions/.packages/.stamps/image.installed": "hash",
}

NEW_TREE = {
    ".update/next/python/wafer-pythonw.exe": "new-python",
    ".update/next/main.py": "new-main",
    ".update/next/Wafer.exe": "new-launcher",
    ".update/next/Uninstaller.exe": "new-uninstaller",
    ".update/next/wafer/_version.py": 'FALLBACK_VERSION = "2.0.0"\n',
    ".update/next/_resources/translations.json": "new-res",
    ".update/next/README.md": "new-readme",
    ".update/next/extensions/image/__init__.py": "new-image",
    ".update/next/extensions/ffmpeg/__init__.py": "new-ffmpeg",
}


@pytest.fixture
def app_root(tmp_path):
    write_tree(tmp_path, OLD_TREE)
    write_tree(tmp_path, NEW_TREE)
    return tmp_path


def replace_targets(ops):
    return [op.dst for op in ops if not op.dst.startswith(".update/")]


class TestValidatePlanRelpath:
    def test_accepts_relative(self):
        assert validate_plan_relpath("extensions/image") == "extensions/image"

    def test_normalizes_backslashes(self):
        assert validate_plan_relpath("extensions\\image") == "extensions/image"

    @pytest.mark.parametrize("bad", ["", "..", "a/../b", "/abs", "C:/x", "a//b", "./a"])
    def test_rejects_unsafe(self, bad):
        with pytest.raises(PlanError):
            validate_plan_relpath(bad)


class TestGeneratePlan:
    def test_python_first_launcher_last(self, app_root):
        ops = generate_plan(app_root)
        targets = replace_targets(ops)
        assert targets[0] == "python"
        assert targets[-1] == "Wafer.exe"
        assert targets[-2] == "Uninstaller.exe"

    def test_never_touches_packages_or_unknown_extensions(self, app_root):
        ops = generate_plan(app_root)
        for op in ops:
            assert ".packages" not in op.src and ".packages" not in op.dst
            assert "myext" not in op.src and "myext" not in op.dst

    def test_lib_carry_op_present(self, app_root):
        ops = generate_plan(app_root)
        carry = [op for op in ops if op.dst == "extensions/ffmpeg/lib"]
        assert len(carry) == 1
        assert carry[0].optional
        assert carry[0].src == ".update/backup/extensions/ffmpeg/lib"

    def test_backup_ops_are_optional(self, app_root):
        ops = generate_plan(app_root)
        for op in ops:
            if op.dst.startswith(".update/backup/"):
                assert op.optional

    def test_removes_dropped_builtin_extension(self, app_root):
        ops = generate_plan(app_root)
        removal = [op for op in ops if op.dst == ".update/backup/extensions/color"]
        assert len(removal) == 1
        assert removal[0].src == "extensions/color"
        assert removal[0].optional
        assert not any(op.dst == "extensions/color" for op in ops)

    def test_missing_staged_tree_raises(self, tmp_path):
        with pytest.raises(PlanError):
            generate_plan(tmp_path)

    def test_staged_update_dir_rejected(self, app_root):
        (app_root / ".update/next/.update").mkdir(parents=True)
        with pytest.raises(PlanError):
            generate_plan(app_root)


class TestPlanSerialization:
    def test_round_trip(self, app_root):
        ops = generate_plan(app_root)
        path = app_root / ".update/apply.plan"
        write_plan(path, ops)
        assert read_plan(path) == ops

    def test_rejects_bad_header(self, tmp_path):
        path = tmp_path / "apply.plan"
        path.write_text("bogus 9\nmove\t0\ta\tb\n", encoding="utf-8")
        with pytest.raises(PlanError):
            read_plan(path)

    def test_rejects_bad_line(self, tmp_path):
        path = tmp_path / "apply.plan"
        path.write_text("wafer-update-plan 1\ncopy\t0\ta\tb\n", encoding="utf-8")
        with pytest.raises(PlanError):
            read_plan(path)

    def test_rejects_traversal_path(self, tmp_path):
        path = tmp_path / "apply.plan"
        path.write_text("wafer-update-plan 1\nmove\t0\t../evil\tb\n", encoding="utf-8")
        with pytest.raises(PlanError):
            read_plan(path)
