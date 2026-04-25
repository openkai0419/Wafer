from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.lang.manager import t
from ...ui.widgets.color_picker import ColorPickerDialog
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...utils.paths import list_data_db_names
from .registry import MarkRegistry


def prompt_new_mark(parent: QtWidgets.QWidget | None = None) -> str | None:
    name, ok = QtWidgets.QInputDialog.getText(parent, t("Add mark"), t("Name:"))
    name = name.strip()
    if not ok or not name:
        return None
    color = ColorPickerDialog.get_color("#888888", parent, t("Choose mark color"), with_alpha=False, scope="mark")
    if color is None:
        return None
    reg = MarkRegistry.instance()
    new_id = reg.add(name, color.name())
    final_name = reg.name_of(new_id)
    if final_name != name:
        Notifier.info(t("Added as '{name}' to avoid duplicate", name=final_name))
    return new_id


def prompt_rename_mark(parent: QtWidgets.QWidget | None, mark_id: str) -> bool:
    reg = MarkRegistry.instance()
    mark = reg.get(mark_id)
    if mark is None:
        return False
    new_name, ok = QtWidgets.QInputDialog.getText(parent, t("Rename mark"), t("Name:"), text=mark.name)
    new_name = new_name.strip()
    if not ok or not new_name or new_name == mark.name:
        return False
    final_name = reg.rename(mark_id, new_name)
    if final_name and final_name != new_name:
        Notifier.info(t("Renamed to '{name}' to avoid duplicate", name=final_name))
    return True


def prompt_pick_color(parent: QtWidgets.QWidget | None, mark_id: str) -> bool:
    reg = MarkRegistry.instance()
    mark = reg.get(mark_id)
    if mark is None:
        return False
    color = ColorPickerDialog.get_color(mark.color, parent, t("Choose mark color"), with_alpha=False, scope="mark")
    if color is None:
        return False
    reg.set_color(mark_id, color.name())
    return True


def confirm_remove_mark(parent: QtWidgets.QWidget | None, mark_id: str) -> bool:
    reg = MarkRegistry.instance()
    mark = reg.get(mark_id)
    if mark is None:
        return False
    if len(reg.marks()) <= 1:
        QtWidgets.QMessageBox.information(parent, t("Remove mark"), t("At least one mark must remain."))
        return False
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(t("Remove mark"))
    layout = QtWidgets.QVBoxLayout(dlg)
    layout.addWidget(QtWidgets.QLabel(t("Remove mark '{name}'?", name=mark.name)))
    purge_cb = QtWidgets.QCheckBox(t("Delete all '{key}' tags from databases", key=MarkRegistry.tag_key(mark_id)))
    layout.addWidget(purge_cb)
    btn_row = QtWidgets.QHBoxLayout()
    btn_row.addStretch()
    confirm_btn = QtWidgets.QPushButton(t("Confirm"))
    cancel_btn = QtWidgets.QPushButton(t("Cancel"))
    confirm_btn.clicked.connect(dlg.accept)
    cancel_btn.clicked.connect(dlg.reject)
    btn_row.addWidget(confirm_btn)
    btn_row.addWidget(cancel_btn)
    layout.addLayout(btn_row)
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return False
    if purge_cb.isChecked():
        _purge_mark_from_all_dbs(mark_id)
    reg.remove(mark_id)
    return True


def show_mark_context_menu(parent: QtWidgets.QWidget, mark_id: str, global_pos: QtCore.QPoint) -> None:
    if MarkRegistry.instance().get(mark_id) is None:
        return
    menu = QtWidgets.QMenu(parent)
    rename_act = menu.addAction(t("Rename..."))
    color_act = menu.addAction(t("Change color..."))
    menu.addSeparator()
    remove_act = menu.addAction(t("Remove..."))
    chosen = menu.exec_(global_pos)
    if chosen is rename_act:
        prompt_rename_mark(parent, mark_id)
    elif chosen is color_act:
        prompt_pick_color(parent, mark_id)
    elif chosen is remove_act:
        confirm_remove_mark(parent, mark_id)


def _purge_mark_from_all_dbs(mark_id: str) -> None:
    from ...core.commands.binding.instance_registry import InstanceRegistry

    node = InstanceRegistry.instance().resolve_node()
    if node is None:
        AppLogger.warning("[Mark] no IPC node for purge")
        return
    names = list_data_db_names()
    if not names:
        return
    key = MarkRegistry.tag_key(mark_id)
    for name in names:
        node.send_reliable("delete.keys", {"keys": [key]}, dst="indexer", db=name)
    AppLogger.info(f"[Mark] Requested purge of '{key}' across {len(names)} db(s)")
