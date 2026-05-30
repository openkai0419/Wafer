from extensions.exiftool.collector import ExifToolCollectorPlugin


def test_exiftool_collector_finalizer_logs_cleanup_failure(monkeypatch):
    from extensions.exiftool import collector as collector_module

    messages = []
    plugin = ExifToolCollectorPlugin()
    monkeypatch.setattr(plugin, "shutdown", lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")))
    monkeypatch.setattr(collector_module, "debug_non_recursive", lambda text: messages.append(text))

    plugin.__del__()

    assert messages == ["[ExifToolCollector] Cleanup failed: cleanup failed"]