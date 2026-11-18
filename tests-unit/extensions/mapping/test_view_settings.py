import threading

from extensions.mapping import view_settings
from extensions.mapping.params import Grouping
from extensions.mapping.view_settings import GroupingStore


def recording_saves(monkeypatch):
    saves = []
    monkeypatch.setattr(view_settings, "save_grouping", lambda db_name, grouping: saves.append((threading.current_thread() is threading.main_thread(), db_name, grouping)))
    return saves


def test_grouping_changes_apply_at_once_and_are_saved_later_off_the_main_thread(qtbot, monkeypatch):
    saves = recording_saves(monkeypatch)
    store = GroupingStore.instance()
    changed = []
    store.changed.connect(changed.append)
    store.set("db", Grouping(size=0.5))
    store.set("db", Grouping(size=2.0))
    assert store.get("db") == Grouping(size=2.0) and changed == ["db", "db"] and saves == []
    qtbot.waitUntil(lambda: bool(saves))
    assert saves == [(False, "db", Grouping(size=2.0))]


def test_pending_grouping_is_saved_when_the_app_quits(monkeypatch):
    saves = recording_saves(monkeypatch)
    store = GroupingStore.instance()
    store.set("db", Grouping(strictness=4.0))
    store.save_pending()
    assert saves == [(True, "db", Grouping(strictness=4.0))] and not store.save_timer.isActive()
    store.save_pending()
    assert len(saves) == 1


def test_a_failed_save_is_logged(qtbot, monkeypatch):
    warnings = []
    monkeypatch.setattr(view_settings.AppLogger, "warning", lambda message, **kwargs: warnings.append(message))

    def broken(db_name, grouping):
        raise OSError("locked")

    monkeypatch.setattr(view_settings, "save_grouping", broken)
    GroupingStore.instance().set("db", Grouping(size=0.5))
    qtbot.waitUntil(lambda: bool(warnings))
    assert "db" in warnings[0]
