from wafer.core.workspace import (
    BarSpec,
    PathPreset,
    QueryPreset,
    UIPreset,
    WindowSlot,
    WorkspaceStore,
)


class TestPresetRoundtrip:
    def test_ui_preset_roundtrip(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        p = UIPreset(name="Default", window_state={"geo": "x"}, component_states={"grid": {"h": 200}})
        store.save_ui_preset(p)
        got = store.get_ui_preset(p.preset_id)
        assert got.name == "Default"
        assert got.window_state == {"geo": "x"}
        assert got.component_states == {"grid": {"h": 200}}
        assert store.list_ui_presets()[0].preset_id == p.preset_id

    def test_path_preset_roundtrip(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        p = PathPreset(name="Photos", database_name="default", expanded=["/a"], selected=["/a/b"])
        store.save_path_preset(p)
        got = store.get_path_preset(p.preset_id)
        assert got.database_name == "default"
        assert got.expanded == ["/a"]
        assert got.selected == ["/a/b"]

    def test_query_preset_roundtrip(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        bars = [BarSpec(filter="text", params={"keywords": "cat"}, op=None, enabled=True),
                BarSpec(filter="text", params={"keywords": "dog"}, op="OR", enabled=True)]
        p = QueryPreset(name="cats+dogs", bars=bars, sort_by="none", ascending=False)
        store.save_query_preset(p)
        got = store.get_query_preset(p.preset_id)
        assert len(got.bars) == 2
        assert got.bars[1].op == "OR"
        assert got.sort_by == "none"

    def test_rename_collision_rejected(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        a = UIPreset(name="A")
        b = UIPreset(name="B")
        store.save_ui_preset(a)
        store.save_ui_preset(b)
        assert store.rename_ui_preset(b.preset_id, "A") is False
        assert store.rename_ui_preset(b.preset_id, "C") is True
        assert store.get_ui_preset(b.preset_id).name == "C"


class TestSlotLifecycle:
    def test_acquire_creates_new_slot(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        sid, slot, existed = store.acquire_slot()
        assert existed is False
        assert sid == slot.slot_id
        assert sid in store.get_active_slot_ids()

    def test_acquire_with_existing_returns_it(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        sid1, _, _ = store.acquire_slot()
        store.release_slot(sid1)
        sid2, slot, existed = store.acquire_slot(sid1)
        assert existed is True
        assert sid2 == sid1

    def test_save_and_get_slot(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        sid, slot, _ = store.acquire_slot()
        slot.name = "Work"
        slot.path = {"database_name": "main", "expanded": [], "selected": []}
        slot.query = {"bars": [], "sort_by": "path", "ascending": False}
        store.save_slot(slot)
        got = store.get_slot(sid)
        assert got.name == "Work"
        assert got.path["database_name"] == "main"

    def test_legacy_slot_without_name_defaults_empty(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        store._locked_update(lambda raw: raw.update({"slots": {"legacy": {"slot_id": "legacy", "path": {"database_name": "db"}}}}))
        assert store.get_slot("legacy").name == ""

    def test_save_slot_preserves_existing_name(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        slot = WindowSlot(slot_id="s1", name="Old", path={"database_name": "old"})
        store.save_slot(slot)
        assert store.rename_slot("s1", "New") is True
        slot.name = "Old"
        slot.path = {"database_name": "new"}
        store.save_slot(slot)

        got = store.get_slot("s1")
        assert got.name == "New"
        assert got.path["database_name"] == "new"

    def test_rename_slot_updates_name_and_allows_duplicates(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        store.save_slot(WindowSlot(slot_id="s1"))
        store.save_slot(WindowSlot(slot_id="s2"))

        assert store.rename_slot("s1", "Shared") is True
        assert store.rename_slot("s2", "Shared") is True
        assert store.get_slot("s1").name == "Shared"
        assert store.get_slot("s2").name == "Shared"

    def test_rename_slot_missing_returns_false(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        assert store.rename_slot("missing", "Name") is False

    def test_release_removes_from_active(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        sid, _, _ = store.acquire_slot()
        store.release_slot(sid)
        assert sid not in store.get_active_slot_ids()

    def test_restore_ids_filtered_by_existence(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        sid, _, _ = store.acquire_slot()
        store.set_restore_slot_ids([sid, "nonexistent"])
        assert store.get_restore_slot_ids() == [sid]

    def test_acquire_with_seed_populates_content(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        seed = {"ui": {"geo": "g"}, "path": {"database_name": "db"}, "query": {"sort_by": "name"}}
        sid, slot, existed = store.acquire_slot(seed=seed)
        assert existed is False
        assert slot.ui == {"geo": "g"}
        assert slot.path == {"database_name": "db"}
        assert slot.query == {"sort_by": "name"}
        assert store.get_slot(sid).path["database_name"] == "db"

    def test_acquire_with_existing_id_ignores_seed(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        sid1, _, _ = store.acquire_slot()
        _, slot, existed = store.acquire_slot(sid1, seed={"ui": {"geo": "x"}})
        assert existed is True
        assert slot.ui == {}

    def test_delete_slot_cleans_active_and_restore(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        sid, _, _ = store.acquire_slot()
        store.set_restore_slot_ids([sid])
        assert store.delete_slot(sid) is True
        assert sid not in store.get_active_slot_ids()
        assert store.get_restore_slot_ids() == []
        assert store.get_slot(sid) is None

    def test_delete_slot_missing_returns_false(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        assert store.delete_slot("missing") is False

    def test_forget_slot_snapshot_keeps_active_and_restore_ids(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        sid, _, _ = store.acquire_slot()
        store.set_restore_slot_ids([sid])

        assert store.forget_slot_snapshot(sid) is True
        raw = store._load_raw()
        assert sid in raw["active_slot_ids"]
        assert sid in raw["restore_slot_ids"]
        assert store.get_restore_slot_ids() == []
        assert store.get_slot(sid) is None

    def test_forget_slot_snapshot_missing_returns_false(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        assert store.forget_slot_snapshot("missing") is False

    def test_reserve_next_window_slot_reuses_latest_inactive_slot(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        old = WindowSlot(slot_id="old", updated_at="2026-04-27T09:00:00+00:00")
        latest = WindowSlot(slot_id="latest", updated_at="2026-04-27T10:00:00+00:00")
        store.save_slot(old)
        store.save_slot(latest)

        sid, slot, existed = store.reserve_next_window_slot()

        assert existed is True
        assert sid == "latest"
        assert slot.slot_id == "latest"
        assert store.get_active_slot_ids() == ["latest"]

    def test_reserve_next_window_slot_excludes_active_slots(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        active = WindowSlot(slot_id="active", updated_at="2026-04-27T11:00:00+00:00")
        inactive = WindowSlot(slot_id="inactive", updated_at="2026-04-27T10:00:00+00:00")
        store.save_slot(active)
        store.save_slot(inactive)
        store.set_active_slot_ids(["active"])

        sid, _, existed = store.reserve_next_window_slot()

        assert existed is True
        assert sid == "inactive"
        assert store.get_active_slot_ids() == ["active", "inactive"]

    def test_reserve_next_window_slot_excludes_restore_slots(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        restoring = WindowSlot(slot_id="restore", updated_at="2026-04-27T11:00:00+00:00")
        inactive = WindowSlot(slot_id="inactive", updated_at="2026-04-27T10:00:00+00:00")
        store.save_slot(restoring)
        store.save_slot(inactive)
        store.set_restore_slot_ids(["restore"])

        sid, _, existed = store.reserve_next_window_slot()

        assert existed is True
        assert sid == "inactive"
        assert store.get_active_slot_ids() == ["inactive"]

    def test_reserve_next_window_slot_creates_new_slot_when_none_available(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        sid, slot, existed = store.reserve_next_window_slot(seed={"path": {"database_name": "main"}})

        assert existed is False
        assert sid == slot.slot_id
        assert store.get_slot(sid).path == {"database_name": "main"}
        assert store.get_active_slot_ids() == [sid]

    def test_reserve_next_window_slot_serializes_repeated_reservations(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        first = WindowSlot(slot_id="first", updated_at="2026-04-27T11:00:00+00:00")
        second = WindowSlot(slot_id="second", updated_at="2026-04-27T10:00:00+00:00")
        store._locked_update(lambda raw: raw.update({"slots": {"first": first.to_dict(), "second": second.to_dict()}}))

        sid1, _, existed1 = store.reserve_next_window_slot()
        sid2, _, existed2 = store.reserve_next_window_slot()

        assert (sid1, existed1) == ("first", True)
        assert (sid2, existed2) == ("second", True)
        assert store.get_active_slot_ids() == ["first", "second"]


class TestPresetOverwrite:
    def test_update_ui_preset_replaces_state_and_keeps_metadata(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        preset = UIPreset(name="U", window_state={"old": 1}, component_states={"grid": {"h": 1}})
        store.save_ui_preset(preset)
        before = store.get_ui_preset(preset.preset_id)

        assert store.update_ui_preset(preset.preset_id, {"new": 2}, {"grid": {"h": 2}}) is True
        got = store.get_ui_preset(preset.preset_id)
        assert got.name == "U"
        assert got.created_at == before.created_at
        assert got.window_state == {"new": 2}
        assert got.component_states == {"grid": {"h": 2}}

    def test_update_path_preset_replaces_path_state(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        preset = PathPreset(name="P", database_name="old", expanded=["/old"], selected=[])
        store.save_path_preset(preset)

        assert store.update_path_preset(preset.preset_id, "new", ["/a"], ["/a/b"]) is True
        got = store.get_path_preset(preset.preset_id)
        assert got.name == "P"
        assert got.database_name == "new"
        assert got.expanded == ["/a"]
        assert got.selected == ["/a/b"]

    def test_update_query_preset_replaces_query_state(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        preset = QueryPreset(name="Q", bars=[BarSpec(filter="text", params={"keywords": "old"})])
        store.save_query_preset(preset)

        bars = [BarSpec(filter="text", params={"keywords": "new"}, op="OR")]
        assert store.update_query_preset(preset.preset_id, bars, "name", True) is True
        got = store.get_query_preset(preset.preset_id)
        assert got.name == "Q"
        assert got.bars[0].params == {"keywords": "new"}
        assert got.bars[0].op == "OR"
        assert got.sort_by == "name"
        assert got.ascending is True

    def test_update_missing_preset_returns_false(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        assert store.update_ui_preset("missing", {}, {}) is False


class TestSnapshot:
    def test_snapshot_returns_all_buckets(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        store.save_ui_preset(UIPreset(name="U"))
        store.save_path_preset(PathPreset(name="P", database_name="d"))
        store.save_query_preset(QueryPreset(name="Q", bars=[]))
        ui, path, query = store.snapshot()
        assert [u.name for u in ui] == ["U"]
        assert [p.name for p in path] == ["P"]
        assert [q.name for q in query] == ["Q"]

    def test_snapshot_empty(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        ui, path, query = store.snapshot()
        assert ui == [] and path == [] and query == []


class TestRecentSlots:
    def test_recent_slots_excludes_active_and_sorts_latest_first(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        first = WindowSlot(slot_id="old", updated_at="2026-04-27T09:00:00+00:00")
        second = WindowSlot(slot_id="new", updated_at="2026-04-27T10:00:00+00:00")
        active = WindowSlot(slot_id="active", updated_at="2026-04-27T11:00:00+00:00")
        store._locked_update(lambda raw: raw.update({"slots": {"old": first.to_dict(), "new": second.to_dict(), "active": active.to_dict()}}))
        store.set_active_slot_ids(["active"])

        assert [s.slot_id for s in store.list_recent_slots(limit=10)] == ["new", "old"]
        assert [s.slot_id for s in store.list_recent_slots(limit=2, include_active=True)] == ["active", "new"]


class TestStoreMtime:
    def test_returns_zero_when_file_missing(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "missing.json"))
        assert store.get_store_mtime() == 0.0

    def test_returns_positive_after_write(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        store.save_ui_preset(UIPreset(name="x"))
        assert store.get_store_mtime() > 0.0

