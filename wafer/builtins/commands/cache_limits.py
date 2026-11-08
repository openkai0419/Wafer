from PySide6 import QtWidgets

from ...core.db.cache_limit import db_cache_limit_mb, save_db_cache_limit
from ...core.files.shared_image_cache import image_cache_limit_mb, set_image_cache_limit
from ...core.lang.manager import t
from ...core.store.settings import app_settings
from ...qt.commands.bridge import ActionKit
from ...qt.widgets.restart_prompt import ask_restart_all

_MINIMUM_MB = 64
_MAXIMUM_MB = 1024 * 1024
_STEP_MB = 64
_DB_SLOW_BELOW_MB = 200


def _limit_box(value: int) -> QtWidgets.QSpinBox:
    box = QtWidgets.QSpinBox()
    box.setRange(_MINIMUM_MB, _MAXIMUM_MB)
    box.setSingleStep(_STEP_MB)
    box.setSuffix(" MiB")
    box.setValue(value)
    return box


def _note(text: str = "") -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    return label


class CacheLimitsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Cache Limits"))
        app_settings.settings.sync()
        self.image_limit = _limit_box(image_cache_limit_mb())
        self.db_limit = _limit_box(db_cache_limit_mb())
        self.db_warning = _note(t("Below 200 MiB, searches get slower."))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        form = QtWidgets.QFormLayout(self)
        form.addRow(t("Image cache (per Viewer)"), self.image_limit)
        form.addRow(_note(t("Thumbnails and full-size images kept in memory, so that images you saw recently open without being read again. Higher is faster and uses more memory.")))
        form.addRow(t("SQLite cache (per process)"), self.db_limit)
        form.addRow(_note(t("Memory SQLite may use for reading and writing the database, in the Viewer, the Indexer and the WebUI. Applies after a restart.")))
        form.addRow(self.db_warning)
        form.addRow(buttons)

        self.db_limit.valueChanged.connect(self.update_db_warning)
        self.update_db_warning()

    def update_db_warning(self) -> None:
        self.db_warning.setVisible(self.db_limit.value() < _DB_SLOW_BELOW_MB)

    def save(self) -> None:
        set_image_cache_limit(self.image_limit.value())
        db_changed = self.db_limit.value() != db_cache_limit_mb()
        if db_changed:
            save_db_cache_limit(self.db_limit.value())
        self.accept()
        if db_changed:
            ask_restart_all(t("The SQLite cache limit has been saved.\nRestart is required."), self.parentWidget())


def open_cache_limits(ctx):
    CacheLimitsDialog(ctx.get("widget") or None).exec()


def cache_limits_command():
    return ActionKit.Command(path="setting.cache_limits", display="Cache Limits...", func=open_cache_limits)


class TrayCacheLimitCommands(ActionKit.MenuBase):
    NAME = ActionKit.MenuPath.SETTING
    SCOPE = "tray"
    PRIORITY = 90

    @classmethod
    def commands(cls):
        return [cache_limits_command()]
