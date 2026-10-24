import socket
import webbrowser

from PySide6 import QtCore, QtGui, QtWidgets

from ...app.webui.settings import HOST_ALL, HOST_LOCAL, LOOPBACK_HOST_NAMES, PRIVATE_NAME_SUFFIXES, WebUISettings, classify_allowed_hosts
from ...qt.commands.bridge import ActionKit, Command
from ...core.platform.process import AppProcess
from ...qt.common.dpi import dpix
from ...qt.common.icon_engine import themed_icon
from ...qt.common.notifier import Notifier
from ...qt.theme import ThemeManager

BUILTIN_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
VISIBLE_ROWS_MIN = 5
VISIBLE_ROWS_MAX = 16


def builtin_host_labels(bind_host: str) -> tuple[str, ...]:
    if bind_host == HOST_LOCAL:
        return LOOPBACK_HOST_NAMES
    return ("IP addresses", f"Names without a dot (this PC: {socket.gethostname()})", *(f"*{suffix}" for suffix in PRIVATE_NAME_SUFFIXES))


class AllowedHostsEditor(QtWidgets.QWidget):
    def __init__(self, hosts: tuple[str, ...], parent=None):
        super().__init__(parent)
        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setMinimumWidth(dpix(300))
        for host in hosts:
            self.list.addItem(self._user_item(host))
        self.list.itemDelegate().closeEditor.connect(self._tidy_rows)
        model = self.list.model()
        model.rowsInserted.connect(self._fit_height)
        model.rowsRemoved.connect(self._fit_height)
        self._fit_height()

        add_btn = QtWidgets.QPushButton()
        add_btn.setIcon(themed_icon("plus"))
        add_btn.setToolTip("Add a host")
        add_btn.clicked.connect(self.add_host)
        remove_btn = QtWidgets.QPushButton()
        remove_btn.setIcon(themed_icon("minus"))
        remove_btn.setToolTip("Remove selected")
        remove_btn.clicked.connect(self.remove_selected)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(add_btn)
        buttons.addWidget(remove_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        layout.addLayout(buttons)

    @staticmethod
    def _user_item(text: str) -> QtWidgets.QListWidgetItem:
        item = QtWidgets.QListWidgetItem(text)
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        return item

    def _fit_height(self, *_args) -> None:
        rows = min(max(self.list.count() + 1, VISIBLE_ROWS_MIN), VISIBLE_ROWS_MAX)
        row_height = self.list.sizeHintForRow(0) if self.list.count() else self.list.fontMetrics().height() + dpix(4)
        self.list.setFixedHeight(rows * row_height + 2 * self.list.frameWidth())

    def set_builtin(self, labels: tuple[str, ...]) -> None:
        for row in reversed(range(self.list.count())):
            if self.list.item(row).data(BUILTIN_ROLE):
                self.list.takeItem(row)
        for row, label in enumerate(labels):
            item = QtWidgets.QListWidgetItem(label)
            item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            item.setData(BUILTIN_ROLE, True)
            item.setToolTip("Always allowed")
            self.list.insertItem(row, item)

    def add_host(self) -> None:
        item = self._user_item("")
        self.list.addItem(item)
        self.list.setCurrentItem(item)
        self.list.editItem(item)

    def _tidy_rows(self, *_args) -> None:
        error = QtGui.QColor(ThemeManager.instance().palette.error)
        for row in reversed(range(self.list.count())):
            item = self.list.item(row)
            if item.data(BUILTIN_ROLE):
                continue
            text = item.text().strip()
            if not text:
                self.list.takeItem(row)
                continue
            parsed = classify_allowed_hosts(text)[0]
            if not parsed:
                item.setForeground(error)
                item.setToolTip("Not a host name. Use a name like example.com or *.example.com. It is not saved.")
                continue
            item.setText(parsed[0])
            item.setData(QtCore.Qt.ItemDataRole.ForegroundRole, None)
            item.setToolTip("")
            for offset, host in enumerate(parsed[1:], start=1):
                self.list.insertItem(row + offset, self._user_item(host))

    def remove_selected(self) -> None:
        for item in self.list.selectedItems():
            if not item.data(BUILTIN_ROLE):
                self.list.takeItem(self.list.row(item))

    def hosts(self) -> tuple[str, ...]:
        texts = [self.list.item(row).text() for row in range(self.list.count()) if not self.list.item(row).data(BUILTIN_ROLE)]
        return classify_allowed_hosts(",".join(texts))[0]


def _window(ctx):
    return ctx.get_instance("WebUIWindow")


def open_browser(ctx=None):
    win = _window(ctx)
    if win:
        webbrowser.open(win.server.browse_url)


def restart_webui(ctx=None):
    Notifier.info("Restarting WebUI...")
    AppProcess.new_main("--webui", "--no-browser", extra_env={"WAFER_REPLACE_WEBUI": "1"})


def open_settings(ctx=None):
    win = _window(ctx)
    settings = WebUISettings()

    dialog = QtWidgets.QDialog(win)
    dialog.setWindowTitle("WebUI Settings")
    form = QtWidgets.QFormLayout(dialog)

    host_combo = QtWidgets.QComboBox()
    host_combo.addItem("Local only (127.0.0.1)", HOST_LOCAL)
    host_combo.addItem("All interfaces (0.0.0.0)", HOST_ALL)
    idx = host_combo.findData(settings.host())
    host_combo.setCurrentIndex(idx if idx >= 0 else 0)

    port_spin = QtWidgets.QSpinBox()
    port_spin.setRange(1, 65535)
    port_spin.setValue(settings.port())

    hosts_editor = AllowedHostsEditor(settings.allowed_hosts())
    hosts_editor.set_builtin(builtin_host_labels(host_combo.currentData()))
    host_combo.currentIndexChanged.connect(lambda: hosts_editor.set_builtin(builtin_host_labels(host_combo.currentData())))

    note = QtWidgets.QLabel('"All interfaces" exposes the WebUI to your network. Securing access is your responsibility.\nChanges apply after restarting the WebUI.')
    note.setWordWrap(True)

    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
    save_btn = buttons.addButton("Save", QtWidgets.QDialogButtonBox.AcceptRole)
    restart_btn = buttons.addButton("Save && Restart", QtWidgets.QDialogButtonBox.ApplyRole)

    form.addRow("Host", host_combo)
    form.addRow("Port", port_spin)
    form.addRow("Allowed hosts", hosts_editor)
    form.addRow(note)
    form.addRow(buttons)

    result = {"restart": False}

    def save():
        settings.save(host_combo.currentData(), port_spin.value(), hosts_editor.hosts())
        dialog.accept()

    save_btn.clicked.connect(save)
    restart_btn.clicked.connect(lambda: (result.__setitem__("restart", True), save()))
    buttons.rejected.connect(dialog.reject)

    if dialog.exec() and result["restart"]:
        Command.run("webui.restart")


class WebUIBackendCommands(ActionKit.MenuBase):
    NAME = ActionKit.MenuPath.PROCESS
    SCOPE = "webui"
    PRIORITY = 84

    @classmethod
    def commands(cls):
        return [
            ":WebUI",
            ActionKit.Command(path="webui.open_browser", display="Open Browser", func=open_browser),
            ActionKit.Command(path="webui.settings", display="Settings...", func=open_settings),
            "-",
            ActionKit.Command(path="webui.restart", display="Restart WebUI", func=restart_webui),
        ]
