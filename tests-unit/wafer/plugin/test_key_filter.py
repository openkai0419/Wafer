import pytest

from wafer.plugin.key_filter import KeyFilter, MODE_BLACKLIST, MODE_WHITELIST


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    ini = tmp_path / "viewer_plugins.ini"
    monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: str(ini))
    monkeypatch.setattr(KeyFilter, "_broadcast_reload", staticmethod(lambda: None))
    KeyFilter._cache = None
    KeyFilter._subscribers = []
    yield
    KeyFilter._cache = None
    KeyFilter._subscribers = []


class TestGet:
    def test_default_is_empty_blacklist(self):
        assert KeyFilter.get("nope") == (MODE_BLACKLIST, frozenset())

    def test_roundtrip(self):
        KeyFilter.set_keys("exif", MODE_WHITELIST, ["a", "b"])
        assert KeyFilter.get("exif") == (MODE_WHITELIST, frozenset({"a", "b"}))


class TestIsEnabled:
    def test_no_filter_all_enabled(self):
        assert KeyFilter.is_enabled("exif", "anything") is True

    def test_blacklist(self):
        KeyFilter.set_keys("exif", MODE_BLACKLIST, ["blocked"])
        assert KeyFilter.is_enabled("exif", "blocked") is False
        assert KeyFilter.is_enabled("exif", "other") is True

    def test_whitelist(self):
        KeyFilter.set_keys("exif", MODE_WHITELIST, ["kept"])
        assert KeyFilter.is_enabled("exif", "kept") is True
        assert KeyFilter.is_enabled("exif", "other") is False


class TestPredicate:
    def test_no_filter_returns_none(self):
        assert KeyFilter.predicate("exif") is None

    def test_empty_blacklist_returns_none(self):
        KeyFilter.set_keys("exif", MODE_BLACKLIST, [])
        assert KeyFilter.predicate("exif") is None

    def test_blacklist_predicate(self):
        KeyFilter.set_keys("exif", MODE_BLACKLIST, ["x"])
        pred = KeyFilter.predicate("exif")
        assert pred("y") is True
        assert pred("x") is False

    def test_whitelist_predicate(self):
        KeyFilter.set_keys("exif", MODE_WHITELIST, ["x"])
        pred = KeyFilter.predicate("exif")
        assert pred("x") is True
        assert pred("y") is False


class TestSetKeyEnabled:
    def test_blacklist_disable_adds_key(self):
        KeyFilter.set_key_enabled("exif", "k", False)
        assert KeyFilter.is_enabled("exif", "k") is False

    def test_blacklist_enable_removes_key(self):
        KeyFilter.set_keys("exif", MODE_BLACKLIST, ["k"])
        KeyFilter.set_key_enabled("exif", "k", True)
        assert KeyFilter.is_enabled("exif", "k") is True

    def test_whitelist_enable_adds_key(self):
        KeyFilter.set_keys("exif", MODE_WHITELIST, [])
        KeyFilter.set_key_enabled("exif", "k", True)
        assert KeyFilter.is_enabled("exif", "k") is True

    def test_whitelist_disable_removes_key(self):
        KeyFilter.set_keys("exif", MODE_WHITELIST, ["k"])
        KeyFilter.set_key_enabled("exif", "k", False)
        assert KeyFilter.is_enabled("exif", "k") is False


class TestApplyKeyStates:
    def test_batch_blacklist(self):
        KeyFilter.apply_key_states("exif", {"a": False, "b": False, "c": True})
        assert KeyFilter.is_enabled("exif", "a") is False
        assert KeyFilter.is_enabled("exif", "b") is False
        assert KeyFilter.is_enabled("exif", "c") is True

    def test_batch_whitelist(self):
        KeyFilter.set_keys("exif", MODE_WHITELIST, [])
        KeyFilter.apply_key_states("exif", {"a": True, "b": False})
        assert KeyFilter.is_enabled("exif", "a") is True
        assert KeyFilter.is_enabled("exif", "b") is False

    def test_empty_is_noop(self):
        seen = []
        KeyFilter.subscribe(seen.append)
        KeyFilter.apply_key_states("exif", {})
        assert seen == []

    def test_single_broadcast(self):
        seen = []
        KeyFilter.subscribe(seen.append)
        KeyFilter.apply_key_states("exif", {"a": False, "b": False})
        assert seen == ["exif"]


class TestBlockedKeys:
    def test_blacklist_from_saved(self):
        KeyFilter.set_keys("exif", MODE_BLACKLIST, ["b", "a"])
        assert KeyFilter.blocked_keys("exif") == ["exif.a", "exif.b"]

    def test_whitelist_from_saved(self):
        KeyFilter.set_keys("exif", MODE_WHITELIST, ["keep"])
        blocked = KeyFilter.blocked_keys("exif", ["keep", "drop1", "drop2"])
        assert blocked == ["exif.drop1", "exif.drop2"]

    def test_explicit_mode_keys_override_saved(self):
        KeyFilter.set_keys("exif", MODE_BLACKLIST, ["saved"])
        blocked = KeyFilter.blocked_keys("exif", mode=MODE_BLACKLIST, keys={"live"})
        assert blocked == ["exif.live"]

    def test_explicit_whitelist(self):
        blocked = KeyFilter.blocked_keys("exif", ["a", "b", "c"], mode=MODE_WHITELIST, keys={"a"})
        assert blocked == ["exif.b", "exif.c"]

    def test_empty_blacklist_is_empty(self):
        assert KeyFilter.blocked_keys("exif") == []


class TestSendDeleteKeys:
    def test_sends_per_db(self, monkeypatch):
        sent = []

        class _Node:
            def send_reliable(self, cmd, payload, dst, db):
                sent.append((cmd, payload, dst, db))

        monkeypatch.setattr(
            "wafer.core.commands.binding.instance_registry.InstanceRegistry.instance",
            classmethod(lambda cls: type("R", (), {"resolve_node": lambda self: _Node()})()),
        )
        KeyFilter.send_delete_keys(["db1", "db2"], ["exif.a"], "exiftool", re_collect=True)
        assert len(sent) == 2
        assert sent[0][0] == "delete.keys"
        assert sent[0][1] == {"keys": ["exif.a"], "collector": "exiftool", "re_collect": True}
        assert {s[3] for s in sent} == {"db1", "db2"}

    def test_no_node_skips(self, monkeypatch):
        monkeypatch.setattr(
            "wafer.core.commands.binding.instance_registry.InstanceRegistry.instance",
            classmethod(lambda cls: type("R", (), {"resolve_node": lambda self: None})()),
        )
        KeyFilter.send_delete_keys(["db1"], ["exif.a"], "exiftool", re_collect=False)


class TestSort:
    def test_default_sort(self):
        assert KeyFilter.read_sort() == (1, False)

    def test_write_read_sort(self):
        KeyFilter.write_sort(0, True)
        KeyFilter._cache = None
        assert KeyFilter.read_sort() == (0, True)


class TestSubscribe:
    def test_notify_called_on_set_keys(self):
        seen = []
        KeyFilter.subscribe(seen.append)
        KeyFilter.set_keys("exif", MODE_BLACKLIST, ["a"])
        assert seen == ["exif"]

    def test_unsubscribe(self):
        seen = []
        KeyFilter.subscribe(seen.append)
        KeyFilter.unsubscribe(seen.append)
        KeyFilter.set_keys("exif", MODE_BLACKLIST, ["a"])
        assert seen == []


class TestReload:
    def test_reload_picks_up_external_write(self):
        KeyFilter.get("exif")
        KeyFilter.set_keys("exif", MODE_WHITELIST, ["a"])
        KeyFilter._cache = None
        KeyFilter.reload()
        assert KeyFilter.get("exif") == (MODE_WHITELIST, frozenset({"a"}))
