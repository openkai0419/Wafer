from wafer.core.state import StateStore


class TestStateStoreSmoke:
    def _fresh_store(self):
        store = StateStore()
        return store

    def test_register_and_save(self):
        store = self._fresh_store()
        saved_data = {"key": "value", "count": 42}
        store.register("ns1", lambda: saved_data, lambda d: None)
        result = store.save_all()
        assert "ns1" in result
        assert result["ns1"]["key"] == "value"
        assert result["ns1"]["count"] == 42

    def test_register_and_restore(self):
        store = self._fresh_store()
        captured = {}
        store.register("ns1", lambda: {}, lambda d: captured.update(d))
        store.restore_all({"ns1": {"restored": True}})
        assert captured["restored"] is True

    def test_multiple_namespaces(self):
        store = self._fresh_store()
        store.register("a", lambda: {"x": 1}, lambda d: None)
        store.register("b", lambda: {"y": 2}, lambda d: None)
        result = store.save_all()
        assert result["a"]["x"] == 1
        assert result["b"]["y"] == 2

    def test_unregister(self):
        store = self._fresh_store()
        store.register("gone", lambda: {"data": 1}, lambda d: None)
        store.unregister("gone")
        result = store.save_all()
        assert "gone" not in result

    def test_deferred_restore(self):
        store = self._fresh_store()
        store.restore_all({"late": {"deferred": True}})
        captured = {}
        store.register("late", lambda: {}, lambda d: captured.update(d))
        assert captured.get("deferred") is True

    def test_save_restore_roundtrip(self):
        store = self._fresh_store()
        state_a = {"mode": "dark", "size": 200}
        state_b = {"scroll": 50, "zoom": 1.5}
        store.register("a", lambda: state_a, lambda d: None)
        store.register("b", lambda: state_b, lambda d: None)
        saved = store.save_all()

        store2 = self._fresh_store()
        captured_a = {}
        captured_b = {}
        store2.register("a", lambda: {}, lambda d: captured_a.update(d))
        store2.register("b", lambda: {}, lambda d: captured_b.update(d))
        store2.restore_all(saved)
        assert captured_a["mode"] == "dark"
        assert captured_b["zoom"] == 1.5

    def test_clear(self):
        store = self._fresh_store()
        store.register("ns", lambda: {"a": 1}, lambda d: None)
        store.clear()
        result = store.save_all()
        assert result == {}

    def test_save_exception_isolated(self):
        store = self._fresh_store()

        def bad_save():
            raise RuntimeError("save error")

        store.register("bad", bad_save, lambda d: None)
        store.register("good", lambda: {"ok": True}, lambda d: None)
        result = store.save_all()
        assert "bad" not in result
        assert result["good"]["ok"] is True

    def test_restore_exception_isolated(self):
        store = self._fresh_store()
        captured = {}

        def bad_restore(d):
            raise RuntimeError("restore error")

        store.register("bad", lambda: {}, bad_restore)
        store.register("good", lambda: {}, lambda d: captured.update(d))
        store.restore_all({"bad": {"x": 1}, "good": {"y": 2}})
        assert captured["y"] == 2

    def test_restore_ignores_non_dict(self):
        store = self._fresh_store()
        captured = {}
        store.register("ns", lambda: {}, lambda d: captured.update(d))
        store.restore_all({"ns": "not_a_dict", "other": 42})
        assert captured == {}
