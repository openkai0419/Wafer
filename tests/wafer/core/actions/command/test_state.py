import pytest
from pathlib import Path

from wafer.core.actions.command.state import (
    CommandOptionStore,
    ActionGroupStateManager,
    PersistentStore,
)
from wafer.core.actions.command.payload import CommandPayload


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

    def test_set_current_and_get_current(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp", "cmd.a")
        mgr.register_member("grp", "cmd.b")
        mgr.set_current("grp", "cmd.b", save=False)
        assert mgr.get_current("grp") == "cmd.b"

    def test_set_current_updates_check_states(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp", "cmd.a")
        mgr.register_member("grp", "cmd.b")
        mgr.set_current("grp", "cmd.a", save=False)
        assert mgr.get_check_state("cmd.a") is True
        assert mgr.get_check_state("cmd.b") is False

    def test_cycle_single_member(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp_single", "cmd.only")
        mgr.set_current("grp_single", "cmd.only", save=False)
        result = mgr.cycle("grp_single", save=False)
        assert result == "cmd.only"

    def test_cycle_two_members(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp2", "cmd.a")
        mgr.register_member("grp2", "cmd.b")
        mgr.set_current("grp2", "cmd.a", save=False)
        result = mgr.cycle("grp2", save=False)
        assert result == "cmd.b"

    def test_cycle_wraps_around(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp3", "cmd.a")
        mgr.register_member("grp3", "cmd.b")
        mgr.register_member("grp3", "cmd.c")
        mgr.set_current("grp3", "cmd.c", save=False)
        result = mgr.cycle("grp3", save=False)
        assert result == "cmd.a"

    def test_cycle_empty_group(self):
        mgr = ActionGroupStateManager.instance()
        result = mgr.cycle("empty_grp", save=False)
        assert result is None

    def test_cycle_no_current_starts_from_first(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp_nocur", "cmd.a")
        mgr.register_member("grp_nocur", "cmd.b")
        result = mgr.cycle("grp_nocur", save=False)
        assert result == "cmd.a"

    def test_initialize_default(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp_def", "cmd.a")
        mgr.register_member("grp_def", "cmd.b")
        mgr.initialize_default("grp_def", "cmd.b")
        assert mgr.get_current("grp_def") == "cmd.b"
        assert mgr.get_check_state("cmd.a") is False
        assert mgr.get_check_state("cmd.b") is True

    def test_initialize_default_does_not_overwrite(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp_d2", "cmd.a")
        mgr.register_member("grp_d2", "cmd.b")
        mgr.set_current("grp_d2", "cmd.a", save=False)
        mgr.initialize_default("grp_d2", "cmd.b")
        assert mgr.get_current("grp_d2") == "cmd.a"

    def test_set_check_state_independent(self):
        mgr = ActionGroupStateManager.instance()
        mgr.set_check_state("cmd.standalone", True)
        assert mgr.get_check_state("cmd.standalone") is True
        mgr.set_check_state("cmd.standalone", False)
        assert mgr.get_check_state("cmd.standalone") is False

    def test_get_check_state_default_false(self):
        mgr = ActionGroupStateManager.instance()
        assert mgr.get_check_state("unregistered") is False

    def test_observer_notified(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp_obs", "cmd.a")
        notifications = []
        mgr.add_observer(lambda g, c: notifications.append((g, c)))
        mgr.set_current("grp_obs", "cmd.a", save=False)
        assert len(notifications) == 1
        assert notifications[0] == ("grp_obs", "cmd.a")

    def test_remove_observer(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp_rem", "cmd.a")
        notifications = []
        obs = lambda g, c: notifications.append((g, c))
        mgr.add_observer(obs)
        mgr.remove_observer(obs)
        mgr.set_current("grp_rem", "cmd.a", save=False)
        assert len(notifications) == 0

    def test_observer_exception_does_not_crash(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp_exc", "cmd.a")

        def broken_observer(g, c):
            raise RuntimeError("observer broke")

        mgr.add_observer(broken_observer)
        mgr.set_current("grp_exc", "cmd.a", save=False)

    def test_commit_roundtrip(self):
        mgr = ActionGroupStateManager.instance()
        mgr.register_member("grp_commit", "cmd.x")
        mgr.register_member("grp_commit", "cmd.y")
        mgr.set_current("grp_commit", "cmd.y", save=False)
        mgr.commit()
        store = CommandOptionStore.instance()
        p = store.get("__group__grp_commit")
        assert p.args.get("selected") == "cmd.y"

    def test_get_members_empty_group(self):
        mgr = ActionGroupStateManager.instance()
        assert mgr.get_members("nonexistent") == []
