from PySide6 import QtWidgets

from ...core.db.cache_limit import db_cache_limit_mb, save_db_cache_limit
from ...core.files.shared_image_cache import image_cache_limit_mb, set_image_cache_limit
from ...core.lang.manager import t
from ...core.platform.workspace_lock import WorkspaceLock
from ...core.store.settings import app_settings
from ...core.store.workspace import WorkspaceStore
from ...qt.commands.bridge import ActionKit

_MINIMUM_MB = 64
_MAXIMUM_MB = 1024 * 1024
_STEP_MB = 64
_DB_SLOW_BELOW_MB = 200


def open_viewer_count() -> int:
    slots = WorkspaceStore.instance().list_slots()
    return len(WorkspaceLock.open_slot_ids([slot.slot_id for slot in slots]))


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
        self.viewer_count = open_viewer_count()
        self.image_limit = _limit_box(image_cache_limit_mb())
        self.image_total = _note()
        self.db_limit = _limit_box(db_cache_limit_mb())
        self.db_warning = _note(t("Below 200 MiB, searches get slower."))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        form = QtWidgets.QFormLayout(self)
        form.addRow(t("Images (per Viewer)"), self.image_limit)
        form.addRow(self.image_total)
        form.addRow(t("Database (per process)"), self.db_limit)
        form.addRow(self.db_warning)
        form.addRow(_note(t("Indexers apply the database limit when they restart. Animated images, Mapping and Zip have their own limits in their menus.")))
        form.addRow(buttons)

        self.image_limit.valueChanged.connect(self.update_notes)
        self.db_limit.valueChanged.connect(self.update_notes)
        self.update_notes()

    def update_notes(self) -> None:
        total = self.image_limit.value() * self.viewer_count
        self.image_total.setText(t("Viewers open: {count}, up to {total} MiB of images").format(count=self.viewer_count, total=total))
        self.db_warning.setVisible(self.db_limit.value() < _DB_SLOW_BELOW_MB)

    def save(self) -> None:
        set_image_cache_limit(self.image_limit.value())
        save_db_cache_limit(self.db_limit.value())
        self.accept()


def open_cache_limits(ctx):
    CacheLimitsDialog(ctx.get("widget") or None).exec()


class CacheLimitCommands(ActionKit.MenuBase):
    NAME = ActionKit.MenuPath.SETTING
    PRIORITY = 91

    @classmethod
    def commands(cls):
        return [
            ":Cache",
            ActionKit.Command(path="setting.cache_limits", display="Cache Limits...", func=open_cache_limits),
        ]


class TrayCacheLimitCommands(CacheLimitCommands):
    SCOPE = "tray"
