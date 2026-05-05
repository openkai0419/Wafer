import py_compile

from wafer.builtins.commands.query import QueryCommands


def _command_paths(items):
    return {str(item.path) for item in items if hasattr(item, "path")}


def test_compile():
    py_compile.compile("wafer/builtins/commands/query.py")


def test_commands_exclude_removed_query_option_commands():
    paths = _command_paths(QueryCommands.commands())

    assert "qry.search" in paths
    assert "qry.toggle_auto_execute" in paths
    assert "qry.toggle_auto_execute_on_update" in paths
    assert "qry.toggle_include_subfolders" in paths
    assert "Sort By/qry.sort_none" in paths
    assert "qry.cycle_sort" in paths
    assert "qry.cycle_order" in paths
    assert "Sort Order/qry.order_asc" in paths
    assert "Sort Order/qry.order_desc" in paths

    assert "Text Mode/qry.mode_glob" not in paths
    assert "Text Mode/qry.mode_like" not in paths
    assert "Join Mode/qry.keyword_and" not in paths
    assert "Join Mode/qry.keyword_or" not in paths
    assert "qry.cycle_mode" not in paths
    assert "qry.cycle_keyword" not in paths
    assert "qry.set_keyword_delimiter" not in paths