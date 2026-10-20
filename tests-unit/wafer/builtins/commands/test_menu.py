import pytest

from wafer.qt.commands.command.maker import MenuMaker
from wafer.qt.commands.command.menu import MenuHub, MenuPath


@pytest.mark.parametrize(
    "command_id, path",
    [
        ("file.copy", "File/file.copy"),
        ("file.select_path", "Selection/file.select_path"),
        ("file.batch_rename", "Selection/Batch Renamer/file.batch_rename"),
        ("file.recollect.files.forget", "Selection/Recollect/Selected Files/file.recollect.files.forget"),
        ("mark.toggle", "Selection/Mark/mark.toggle"),
        ("qry.search", "Query/qry.search"),
        ("setting.plugin_manager", "Widgets/setting.plugin_manager"),
        ("setting.batch_renamer", "Widgets/setting.batch_renamer"),
        ("ft.next_folder", "Widgets/FolderTree/ft.next_folder"),
        ("grid.select_all", "Widgets/GridView/grid.select_all"),
        ("fv.next_file", "Widgets/FileViewer/fv.next_file"),
        ("imgv.zoom_in", "Widgets/FileViewer/imgv.zoom_in"),
        ("win.toggle_fullscreen", "Widgets/Window/win.toggle_fullscreen"),
        ("showfilemenu", "Widgets/Menus/showfilemenu"),
        ("panel.solo", "Panel/panel.solo"),
        ("ui_preset.save_current", "Workspace/ui_preset.save_current"),
        ("db.next_database", "Workspace/db.next_database"),
        ("win.restart_all", "Process/win.restart_all"),
        ("setting.keybind", "Setting/setting.keybind"),
        ("update.check", "Setting/update.check"),
        ("help.about", "Setting/help.about"),
    ],
)
def test_builtin_commands_sit_in_their_menu(command_id, path):
    assert MenuHub.instance().get_path_by_command_id(command_id) == path


def test_show_file_is_also_placed_in_the_grid_view_menu():
    assert "show_file" in " ".join(MenuMaker().from_folder(MenuPath.GRID_VIEW).resolve_tokens())
    assert MenuHub.instance().get_path_by_command_id("file.show_file") == "Selection/file.show_file"


def test_allmenu_is_bindable_but_not_listed():
    tokens = MenuMaker().from_folder(MenuPath.MENUS).resolve_tokens()
    assert "showfilemenu" in tokens
    assert "allmenu" not in tokens


def test_viewer_top_level_menus_are_the_fixed_roots():
    roots = []
    for token in MenuMaker().all_roots().resolve_tokens():
        root = token.split("/")[0]
        if root not in roots:
            roots.append(root)
    assert [r for r in roots if r in MenuPath.ROOTS] == list(MenuPath.ROOTS)
    assert roots[: len(MenuPath.ROOTS)] == list(MenuPath.ROOTS)


def test_widgets_lists_general_folders_before_the_panel_folders():
    submenus = []
    for token in MenuMaker().from_folder(MenuPath.WIDGETS).resolve_tokens():
        parts = token.split("/")
        if len(parts) > 1 and parts[0] not in submenus:
            submenus.append(parts[0])
    assert submenus[:5] == ["Window", "Menus", "FolderTree", "GridView", "FileViewer"]
