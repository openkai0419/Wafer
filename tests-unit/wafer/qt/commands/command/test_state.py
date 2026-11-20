import pytest

from wafer.qt.commands.command.state import (
    CommandOptionStore,
    PersistentStore,
)
from wafer.qt.commands.command.payload import CommandPayload


@pytest.fixture(autouse=True)
def _isolate_option_store(tmp_path):
    prev_inst = CommandOptionStore._instance
    prev_path = CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore.configure(tmp_path / "opts.json")
    yield
    CommandOptionStore._instance = prev_inst
    CommandOptionStore._default_path = prev_path


class TestPersistentStore:
    def test_set_and_get(self, tmp_path):
        store = PersistentStore(tmp_path / "test.json")
        store._set_raw("key1", {"a": 1})
        assert store._get_raw("key1") == {"a": 1}

    def test_get_missing_key(self, tmp_path):
        store = PersistentStore(tmp_path / "test.json")
        assert store._get_raw("missing") == {}

    def test_clear_specific_key(self, tmp_path):
        store = PersistentStore(tmp_path / "test.json")
        store._set_raw("key1", {"a": 1})
        store.commit()
        store.clear("key1")
        assert store._get_raw("key1") == {}

    def test_clear_all(self, tmp_path):
        store = PersistentStore(tmp_path / "test.json")
        store._set_raw("key1", {"a": 1})
        store._set_raw("key2", {"b": 2})
        store.clear()
        assert store._get_raw("key1") == {}
        assert store._get_raw("key2") == {}

    def test_buffer_overrides_map(self, tmp_path):
        store = PersistentStore(tmp_path / "test.json")
        store._set_raw("key1", {"a": 1})
        store.commit()
        store._set_raw("key1", {"a": 2})
        assert store._get_raw("key1") == {"a": 2}

    def test_commit_when_no_pending(self, tmp_path):
        store = PersistentStore(tmp_path / "test.json")
        assert store.commit() is True


class TestCommandOptionStore:
    def test_get_returns_payload(self):
        store = CommandOptionStore.instance()
        store.set("cmd.test", {"step": 5})
        p = store.get("cmd.test")
        assert isinstance(p, CommandPayload)
        assert p.args.get("step") == 5

    def test_get_missing_returns_empty_payload(self):
        store = CommandOptionStore.instance()
        p = store.get("nonexistent")
        assert isinstance(p, CommandPayload)
        assert p.id == "nonexistent"
        assert p.args == {}

    def test_set_with_command_payload(self):
        store = CommandOptionStore.instance()
        store.set("cmd.test", CommandPayload("cmd.test", {"x": 42}))
        p = store.get("cmd.test")
        assert p.args.get("x") == 42

    def test_commit_and_reload(self, tmp_path):
        store_path = tmp_path / "reload_opts.json"
        prev_inst = CommandOptionStore._instance
        CommandOptionStore._instance = None
        CommandOptionStore.configure(store_path)
        store = CommandOptionStore.instance()
        store.set("cmd.r", {"val": 99})
        store.commit()

        CommandOptionStore._instance = None
        CommandOptionStore.configure(store_path)
        store2 = CommandOptionStore.instance()
        p = store2.get("cmd.r")
        assert p.args.get("val") == 99

        CommandOptionStore._instance = prev_inst


class TestStoresSharingAFile:
    def test_saving_keeps_options_another_viewer_saved(self, tmp_path):
        path = tmp_path / "shared.json"
        a = PersistentStore(path)
        b = PersistentStore(path)
        a._get_raw("x")
        b._get_raw("y")
        a._set_raw("x", {"v": 1})
        assert a.commit()
        b._set_raw("y", {"v": 2})
        assert b.commit()
        assert PersistentStore(path)._get_raw("x") == {"v": 1}
        assert PersistentStore(path)._get_raw("y") == {"v": 2}

    def test_saving_does_not_roll_back_a_newer_value_of_another_key(self, tmp_path):
        path = tmp_path / "shared.json"
        a = PersistentStore(path)
        a._set_raw("x", {"v": 1})
        a.commit()
        b = PersistentStore(path)
        b._get_raw("x")
        a._set_raw("x", {"v": 2})
        a.commit()
        b._set_raw("y", {"v": 3})
        b.commit()
        assert PersistentStore(path)._get_raw("x") == {"v": 2}
        assert b._get_raw("x") == {"v": 2}

    def test_clear_removes_only_the_key_from_the_shared_file(self, tmp_path):
        path = tmp_path / "shared.json"
        a = PersistentStore(path)
        b = PersistentStore(path)
        a._get_raw("x")
        b._set_raw("y", {"v": 2})
        b.commit()
        a._set_raw("x", {"v": 1})
        a.commit()
        a.clear("x")
        fresh = PersistentStore(path)
        assert fresh._get_raw("x") == {}
        assert fresh._get_raw("y") == {"v": 2}
