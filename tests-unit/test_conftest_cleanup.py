def test_record_cleanup_error_keeps_message_and_logs(monkeypatch):
    import conftest

    messages = []
    previous = list(conftest._cleanup_errors)
    conftest._cleanup_errors.clear()
    monkeypatch.setattr(conftest.AppLogger, "debug", lambda text: messages.append(text))

    try:
        conftest._record_cleanup_error("cleanup step", RuntimeError("failed"))
        assert conftest._cleanup_errors == ["cleanup step: failed"]
        assert messages == ["[test cleanup] cleanup step: failed"]
    finally:
        conftest._cleanup_errors[:] = previous