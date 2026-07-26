from __future__ import annotations

import uuid

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.commands.bridge import ActionKit, Menu
from ...core.db.dispatch import send_to_db_scope
from ...core.db.key_value import SCOPE_META_INFO, SCOPE_TAG, normalize_data_scope, other_data_scope
from ...core.lang.manager import t
from ...core.qt.badge_engine import badge_shape_keys, badge_shape_pixmap, normalize_badge_shape_key
from ...core.qt.icon_engine import themed_icon
from ...ui.widgets.color_picker import ColorPickerDialog
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from .registry import MarkRegistry
from .shapes import DEFAULT_SHAPE_KEY


def _normalize_mark_scope(scope: str) -> str:
    try:
        selected_scope = normalize_data_scope(scope)
    except ValueError:
        selected_scope = SCOPE_META_INFO
    if selected_scope not in (SCOPE_META_INFO, SCOPE_TAG):
        return SCOPE_META_INFO
    return selected_scope


def _prompt_new_mark_values(parent: QtWidgets.QWidget | None = None, *, scope: str = SCOPE_META_INFO) -> tuple[str | None, str, str]:
    selected_scope = _normalize_mark_scope(scope)
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(t("Add mark"))
    dlg.resize(dpix(420), dpix(140))

    layout = QtWidgets.QVBoxLayout(dlg)
    layout.setContentsMargins(dpix(12), dpix(12), dpix(12), dpix(12))
    layout.setSpacing(dpix(8))

    form = QtWidgets.QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(dpix(8))

    name_edit = QtWidgets.QLineEdit(dlg)
    name_edit.setClearButtonEnabled(True)
    form.addRow(t("Name:"), name_edit)

    scope_combo = QtWidgets.QComboBox(dlg)
    scope_combo.addItem(t("Mark (metadata / path scoped)"), SCOPE_META_INFO)
    scope_combo.addItem(t("Tag (hash scoped)"), SCOPE_TAG)
    scope_combo.setCurrentIndex(max(0, scope_combo.findData(selected_scope)))
    form.addRow(t("Create as:"), scope_combo)
    layout.addLayout(form)

    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
        parent=dlg,
    )
    add_btn = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
    if add_btn is not None:
        add_btn.setText(t("Add"))
        add_btn.setEnabled(False)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)

    if add_btn is not None:
        name_edit.textChanged.connect(lambda text: add_btn.setEnabled(bool(text.strip())))

    name_edit.setFocus()
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return None, selected_scope, DEFAULT_SHAPE_KEY

    name = name_edit.text().strip()
    if not name:
        return None, selected_scope, DEFAULT_SHAPE_KEY
    return name, _normalize_mark_scope(scope_combo.currentData()), DEFAULT_SHAPE_KEY


def prompt_new_mark(parent: QtWidgets.QWidget | None = None, *, scope: str = SCOPE_META_INFO) -> str | None:
    name, selected_scope, shape_key = _prompt_new_mark_values(parent, scope=scope)
    if not name:
        return None
    color = ColorPickerDialog.get_color("#888888", parent, t("Choose mark color"), with_alpha=False, scope="mark")
    if color is None:
        return None
    reg = MarkRegistry.instance()
    new_id = reg.add(name, color.name(), storage_scope=selected_scope, shape_key=shape_key)
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


def prompt_pick_shape(parent: QtWidgets.QWidget | None, mark_id: str) -> bool:
    reg = MarkRegistry.instance()
    mark = reg.get(mark_id)
    if mark is None:
        return False
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(t("Choose mark shape"))
    layout = QtWidgets.QVBoxLayout(dlg)
    layout.setContentsMargins(dpix(12), dpix(12), dpix(12), dpix(12))
    combo = QtWidgets.QComboBox(dlg)
    _populate_shape_keys(combo, mark.shape_key, color=mark.color)
    layout.addWidget(combo)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
        parent=dlg,
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return False
    new_key = normalize_badge_shape_key(combo.currentData() or combo.currentText())
    if new_key == mark.shape_key:
        return False
    reg.set_shape_key(mark_id, new_key)
    return True


def _populate_shape_keys(combo: QtWidgets.QComboBox, current: str, *, color: str = "#888888") -> None:
    icon_size = dpix(16)
    qcolor = QtGui.QColor(color or "#888888")
    combo.clear()
    for key in badge_shape_keys():
        combo.addItem(QtGui.QIcon(badge_shape_pixmap(key, icon_size, qcolor)), key, userData=key)
    idx = combo.findData(normalize_badge_shape_key(current))
    if idx >= 0:
        combo.setCurrentIndex(idx)


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
    purge_cb = QtWidgets.QCheckBox(t("Delete all '{key}' entries from databases", key=MarkRegistry.key(mark_id)))
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
    uid = f"{id(parent):x}.{mark_id}"
    spec = Menu.session(parent).menu(
        [
            ":Mark",
            ActionKit.Action(path=f"inline.mark.{uid}.rename", display="Rename...", func=lambda ctx: prompt_rename_mark(parent, mark_id)),
            ActionKit.Action(path=f"inline.mark.{uid}.color", display="Change color...", func=lambda ctx: prompt_pick_color(parent, mark_id)),
            ActionKit.Action(path=f"inline.mark.{uid}.shape", display="Change shape...", func=lambda ctx: prompt_pick_shape(parent, mark_id)),
            "-",
            ActionKit.Action(path=f"inline.mark.{uid}.scope", display="Scope / Convert...", func=lambda ctx: show_mark_management_dialog(parent, mark_id)),
            "-",
            ActionKit.Action(path=f"inline.mark.{uid}.remove", display="Remove...", func=lambda ctx: confirm_remove_mark(parent, mark_id)),
        ]
    )
    if spec is not None:
        spec.exec(global_pos)


def show_mark_management_dialog(parent: QtWidgets.QWidget | None, mark_id: str) -> bool:
    reg = MarkRegistry.instance()
    if reg.get(mark_id) is None:
        return False
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(t("Mark scope"))
    dlg.resize(dpix(520), dpix(220))

    layout = QtWidgets.QVBoxLayout(dlg)
    layout.setContentsMargins(dpix(12), dpix(12), dpix(12), dpix(12))
    layout.setSpacing(dpix(8))

    title = QtWidgets.QLabel(dlg)
    title.setStyleSheet(f"font-weight: bold; padding-bottom: {dpix(2)}px;")
    layout.addWidget(title)

    form = QtWidgets.QFormLayout()
    scope_combo = QtWidgets.QComboBox(dlg)
    scope_combo.addItem(t("Metadata (path scoped)"), SCOPE_META_INFO)
    scope_combo.addItem(t("Tag (hash scoped)"), SCOPE_TAG)
    current_scope = reg.scope_of(mark_id)
    scope_combo.setCurrentIndex(max(0, scope_combo.findData(current_scope)))
    form.addRow(t("Preferred write scope:"), scope_combo)

    form.addRow(t("Convert target:"), QtWidgets.QLabel(t("All databases"), dlg))
    layout.addLayout(form)

    warning = QtWidgets.QLabel(dlg)
    warning.setWordWrap(True)
    layout.addWidget(warning)

    buttons = QtWidgets.QDialogButtonBox(dlg)
    convert_btn = buttons.addButton(t("Save / Convert"), QtWidgets.QDialogButtonBox.ActionRole)
    close_btn = buttons.addButton(QtWidgets.QDialogButtonBox.Close)
    convert_btn.setIcon(themed_icon("save"))
    close_btn.clicked.connect(dlg.accept)
    layout.addWidget(buttons)

    def refresh():
        mark = reg.get(mark_id)
        if mark is None:
            dlg.accept()
            return
        title.setText(t("Mark: {name}", name=mark.name))
        selected = normalize_data_scope(scope_combo.currentData())
        from_scope = other_data_scope(selected)
        warning.setText(
            t(
                "Save / Convert saves this mark's preferred write scope and sends a conversion request from {from_scope} to {to_scope}. Tag data is shared by file hash; metadata is stored per path. The request is asynchronous and can be run again after errors or shutdowns.",
                from_scope=from_scope,
                to_scope=selected,
            )
        )

    def convert():
        selected = normalize_data_scope(scope_combo.currentData())
        from_scope = other_data_scope(selected)
        key = MarkRegistry.key(mark_id)
        ok = QtWidgets.QMessageBox.question(
            dlg,
            t("Save / Convert mark"),
            t(
                "Save the preferred scope and send conversion for '{key}' from {from_scope} to {to_scope}?\n\nThis does not wait for every database response. You can run it again at any time.",
                key=key,
                from_scope=from_scope,
                to_scope=selected,
            ),
        )
        if ok != QtWidgets.QMessageBox.Yes:
            return
        reg.set_scope(mark_id, selected)
        sent = _send_convert_scope(mark_id, selected, "*")
        Notifier.info(t("Conversion requested for {count} database(s)", count=sent))
        refresh()

    scope_combo.currentIndexChanged.connect(lambda _idx: refresh())
    convert_btn.clicked.connect(convert)
    refresh()
    return dlg.exec() == QtWidgets.QDialog.Accepted


def _send_convert_scope(mark_id: str, to_scope: str, db_scope: str = "*") -> int:
    from ...core.commands.binding.instance_registry import InstanceRegistry

    node = InstanceRegistry.instance().resolve_node()
    if node is None:
        AppLogger.warning("[Mark] no IPC node for scope conversion")
        return 0
    key = MarkRegistry.key(mark_id)
    return send_to_db_scope(
        node,
        "kv.convert_scope",
        {"key": key, "to_scope": to_scope, "request_id": uuid.uuid4().hex},
        db_scope=db_scope or "*",
    )


def _purge_mark_from_all_dbs(mark_id: str) -> None:
    from ...core.db.recollect import Recollect

    key = MarkRegistry.key(mark_id)
    sent = Recollect.purge(db_scope="*", keys=[key], delete=False)
    AppLogger.info(f"[Mark] Requested purge of '{key}' across {sent} db(s)")
