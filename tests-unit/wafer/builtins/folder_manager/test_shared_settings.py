import pytest

from wafer.builtins.folder_manager import shared_settings
from wafer.builtins.folder_manager.rules import HighlightRule, default_rules
from wafer.builtins.folder_manager.shared_settings import (
    COLUMNS_KEY,
    DATABASE_KEY,
    DEFAULT_COLUMNS,
    RULES_KEY,
    load_columns,
    load_last_database,
    load_rules,
    save_columns,
    save_last_database,
    save_rules,
)
from wafer.core.store.settings import app_settings

KEYS = (RULES_KEY, COLUMNS_KEY, DATABASE_KEY)


def clear_keys() -> None:
    app_settings.discard()
    for key in KEYS:
        app_settings.settings.remove(key)
    app_settings.settings.sync()


@pytest.fixture(autouse=True)
def clean_keys(monkeypatch):
    def commit_now():
        snapshot = dict(app_settings._buffer)
        app_settings._buffer.clear()
        app_settings._saver.set_buffer(snapshot)
        app_settings._saver.flush()

    monkeypatch.setattr(app_settings, "commit", commit_now)
    clear_keys()
    yield
    clear_keys()


def test_keys():
    assert RULES_KEY == "folder_manager/rules"
    assert COLUMNS_KEY == "folder_manager/columns"
    assert DATABASE_KEY == "folder_manager/database"


def test_missing_rules_give_default_rules():
    assert [r.to_dict() for r in load_rules()] == [r.to_dict() for r in default_rules()]


def test_rules_round_trip_and_empty_stays_empty():
    rules = default_rules()[:2]
    save_rules(rules)
    assert [r.to_dict() for r in load_rules()] == [r.to_dict() for r in rules]
    save_rules([])
    assert load_rules() == []


def test_broken_rule_is_skipped_with_warning(monkeypatch):
    good = default_rules()[0].to_dict()
    app_settings.set(RULES_KEY, [good, {"bogus": 1}, 5])
    warnings = []
    monkeypatch.setattr(shared_settings.AppLogger, "warning", lambda message: warnings.append(message))
    loaded = load_rules()
    assert [r.to_dict() for r in loaded] == [good]
    assert len(warnings) == 2
    assert all(isinstance(r, HighlightRule) for r in loaded)


def test_columns_default_and_round_trip_and_fill():
    assert load_columns() == DEFAULT_COLUMNS
    save_columns({"files": False})
    assert load_columns() == {**DEFAULT_COLUMNS, "files": False}


def test_columns_not_a_dict_warns_and_uses_default(monkeypatch):
    app_settings.set(COLUMNS_KEY, 7)
    warnings = []
    monkeypatch.setattr(shared_settings.AppLogger, "warning", lambda message: warnings.append(message))
    assert load_columns() == DEFAULT_COLUMNS
    assert len(warnings) == 1


def test_last_database_round_trip():
    assert load_last_database() == ""
    save_last_database("main")
    assert load_last_database() == "main"
