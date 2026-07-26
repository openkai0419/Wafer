from wafer.core.commands.command.core import CommandRegistry
from wafer.builtins.commands.recollect import FileRecollectCommands, _folder_prefixes
from wafer.utils.paths import normalize_path


def test_recollect_commands_register_all_12_paths(qtbot):
    FileRecollectCommands.register()
    reg = CommandRegistry.instance()
    for scope in ("files", "folder", "db", "all_db"):
        for op in ("reset_prefix", "reset_all", "forget"):
            assert reg.has_command(f"file.recollect.{scope}.{op}")


def test_folder_prefixes_derives_parent_of_selected_files(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.jpg").write_bytes(b"x")
    ctx = {"sources": [str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")]}
    assert _folder_prefixes(ctx) == [normalize_path(str(tmp_path))]


def test_folder_prefixes_keeps_selected_folder_as_is(tmp_path):
    ctx = {"path": str(tmp_path)}
    assert _folder_prefixes(ctx) == [normalize_path(str(tmp_path))]


def test_folder_prefixes_skips_virtual_paths(tmp_path):
    ctx = {"sources": [f"{tmp_path}/a.zip::inner.jpg"]}
    assert _folder_prefixes(ctx) == []
