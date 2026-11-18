from __future__ import annotations


def test_activate_does_not_write_binding_files(tmp_path):
    from wafer.qt.commands.binding.manager import BindingManager
    from wafer.qt.commands.bridge import Settings
    from wafer.qt.commands.command.state import CommandOptionStore

    prev_settings_instance = getattr(Settings, "_instance", None)
    prev_settings_configured = getattr(Settings, "_configured", False)
    prev_binding_manager_instance = getattr(BindingManager, "_instance", None)
    prev_cmdopt_instance = getattr(CommandOptionStore, "_instance", None)
    prev_cmdopt_initialized = getattr(CommandOptionStore, "_initialized", False)
    prev_cmdopt_default_path = getattr(CommandOptionStore, "_default_path", None)

    try:
        mouse_path = tmp_path / "binding" / "mouse_bindings.json"
        key_path = tmp_path / "binding" / "key_bindings.json"
        options_path = tmp_path / "binding" / "command_options.json"

        Settings._instance = None
        Settings._configured = False
        BindingManager._instance = None
        CommandOptionStore._instance = None
        CommandOptionStore._initialized = False
        CommandOptionStore._default_path = None

        Settings.configure(
            mouse_bindings=mouse_path,
            key_bindings=key_path,
            command_options=options_path,
        )
        Settings.activate()

        assert not mouse_path.exists()
        assert not key_path.exists()
        assert not options_path.exists()
    finally:
        Settings._instance = prev_settings_instance
        Settings._configured = prev_settings_configured
        BindingManager._instance = prev_binding_manager_instance
        CommandOptionStore._instance = prev_cmdopt_instance
        CommandOptionStore._initialized = prev_cmdopt_initialized
        CommandOptionStore._default_path = prev_cmdopt_default_path


def test_activate_reads_each_binding_file_once(tmp_path, monkeypatch):
    from wafer.qt.commands.binding.manager import BindingManager
    from wafer.qt.commands.binding.store_base import BindingStoreBase
    from wafer.qt.commands.bridge import Settings
    from wafer.qt.commands.command.state import CommandOptionStore

    prev_settings_instance = Settings._instance
    prev_settings_configured = Settings._configured
    prev_binding_manager_instance = BindingManager._instance
    prev_cmdopt_instance = CommandOptionStore._instance
    prev_cmdopt_default_path = CommandOptionStore._default_path
    loads = []
    original = BindingStoreBase.load_from_file
    monkeypatch.setattr(BindingStoreBase, "load_from_file", lambda self, path: loads.append(path) or original(self, path))
    try:
        Settings._instance = None
        Settings._configured = False
        BindingManager._instance = None
        CommandOptionStore._instance = None
        Settings.configure(
            mouse_bindings=tmp_path / "mouse.json",
            key_bindings=tmp_path / "key.json",
            command_options=tmp_path / "opts.json",
        )
        Settings.activate()
        assert sorted(loads) == sorted([str(tmp_path / "mouse.json"), str(tmp_path / "key.json")])
    finally:
        Settings._instance = prev_settings_instance
        Settings._configured = prev_settings_configured
        BindingManager._instance = prev_binding_manager_instance
        CommandOptionStore._instance = prev_cmdopt_instance
        CommandOptionStore._default_path = prev_cmdopt_default_path
