class StartupTasks:
    def __init__(self, *, headless: bool = False):
        self._headless = headless

    def run(self, on_ready=None) -> None:
        self._verify_resources()
        if self._headless:
            self._log_update_check()
            return
        self._schedule_update_check()
        if on_ready is not None:
            on_ready(self.prompt_plugin_setup)
        else:
            from PySide6 import QtCore

            QtCore.QTimer.singleShot(0, self.prompt_plugin_setup)

    @staticmethod
    def _verify_resources() -> None:
        from ..core.logs import AppLogger
        from ..core.common.paths import get_resource_path

        resources = get_resource_path()
        if not resources.is_dir():
            AppLogger.error(f"Resource directory is missing: {resources}. Translations, key bindings and icons will fail to load. Reinstall or run from the application root.")

    def _schedule_update_check(self) -> None:
        from ..builtins.updater.startup import schedule_startup_update_check

        schedule_startup_update_check()

    def _log_update_check(self) -> None:
        from ..builtins.updater.startup import log_startup_update_check

        log_startup_update_check()

    @staticmethod
    def prompt_plugin_setup() -> None:
        from ..plugin.setup_prompt import plugin_setup_needed

        if not plugin_setup_needed():
            return
        from ..builtins.commands.panel import open_panel

        open_panel(name="Plugin Manager", toggle=False)
