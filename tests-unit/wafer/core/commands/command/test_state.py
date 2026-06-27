import pytest
from types import SimpleNamespace

from wafer.core.commands.command.state import (
    CommandOptionStore,
    ActionGroupStateManager,
    PersistentStore,
)
from wafer.core.commands.command.payload import CommandPayload


@pytest.fixture(autouse=True)
def _isolate_option_store(tmp_path):
    prev_inst = CommandOptionStore._instance
    prev_path = CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore.configure(tmp_path / "opts.json")
    yield
    CommandOptionStore._instance = prev_inst
    CommandOptionStore._default_path = prev_path


@pytest.fixture(autouse=True)
def _isolate_state_manager():
    prev = ActionGroupStateManager._instance
    ActionGroupStateManager._instance = None
    yield
    ActionGroupStateManager._instance = prev


class TestPersistentStore:
    def test_set_and_get(self, tmp_path):
        store = PersistentStore(tmp_path / "test.json")
        store._set_raw("key1", {"a": 1})
        assert store._get_raw("key1") == {"a": 1}

    def test_commit_writes_to_file(self, tmp_path):
        p = tmp_path / "test.json"
        store = PersistentStore(p)
        store._set_raw("key1", {"a": 1})
        store.commit()
        assert p.exists()

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

    def test_set_with_dict(self):
        store = CommandOptionStore.instance()
        store.set("cmd.test", {"y": 10})
        p = store.get("cmd.test")
        assert p.args.get("y") == 10

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

    def test_configure_creates_singleton(self, tmp_path):
        s1 = CommandOptionStore.instance()
        s2 = CommandOptionStore.instance()
        assert s1 is s2


class _FakeRegistry:
    def __init__(self, members: dict[str, dict]):
        self._members = members

    def get_command(self, cmd_id):
        spec = self._members.get(cmd_id)
        if spec is None:
            return None
        meta = SimpleNamespace(checked=spec.get("resolver"))
        return SimpleNamespace(meta=meta)


class TestActionGroupStateManager:
    def test_register_and_get_members(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp", "cmd.a")
        mgr.register_member("grp", "cmd.b")
        assert mgr.get_members("grp") == ["cmd.a", "cmd.b"]

    def test_register_member_prevents_duplicate(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp", "cmd.a")
        mgr.register_member("grp", "cmd.a")
        assert mgr.get_members("grp") == ["cmd.a"]

    def test_get_group_for_command(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp", "cmd.a")
        assert mgr.get_group_for_command("cmd.a") == "grp"

    def test_get_group_for_unknown_command(self):
        mgr = ActionGroupStateManager.instance()
        assert mgr.get_group_for_command("nonexistent") is None

    def test_get_members_empty_group(self):
        mgr = ActionGroupStateManager.instance()
        assert mgr.get_members("nonexistent") == []

    def test_find_current_returns_resolver_match(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp", "cmd.a")
        mgr.register_member("grp", "cmd.b")
        registry = _FakeRegistry({
            "cmd.a": {"resolver": lambda: False},
            "cmd.b": {"resolver": lambda: True},
        })
        assert mgr.find_current("grp", registry) == "cmd.b"

    def test_find_current_returns_first_truthy(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp", "cmd.a")
        mgr.register_member("grp", "cmd.b")
        mgr.register_member("grp", "cmd.c")
        registry = _FakeRegistry({
            "cmd.a": {"resolver": lambda: False},
            "cmd.b": {"resolver": lambda: True},
            "cmd.c": {"resolver": lambda: True},
        })
        assert mgr.find_current("grp", registry) == "cmd.b"

    def test_find_current_no_default_no_resolver_match(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp", "cmd.a")
        registry = _FakeRegistry({"cmd.a": {"resolver": lambda: False}})
        assert mgr.find_current("grp", registry) is None

    def test_find_current_handles_resolver_exception(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp", "cmd.a")
        mgr.register_member("grp", "cmd.b")

        def broken():
            raise RuntimeError("resolver failed")

        registry = _FakeRegistry({
            "cmd.a": {"resolver": broken},
            "cmd.b": {"resolver": lambda: True},
        })
        assert mgr.find_current("grp", registry) == "cmd.b"

    def test_find_current_empty_group(self):
        mgr = ActionGroupStateManager.instance()
        registry = _FakeRegistry({})
        assert mgr.find_current("nonexistent", registry) is None
