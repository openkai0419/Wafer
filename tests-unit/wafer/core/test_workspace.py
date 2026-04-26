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
        p = UIPreset(name="Default", color="#4A90D9", window_state={"geo": "x"}, component_states={"grid": {"h": 200}})
        store.save_ui_preset(p)
        got = store.get_ui_preset(p.preset_id)
        assert got.name == "Default"
        assert got.color == "#4A90D9"
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
        p = QueryPreset(name="cats+dogs", bars=bars, include_sort=True, sort_by="path", ascending=False)
        store.save_query_preset(p)
        got = store.get_query_preset(p.preset_id)
        assert len(got.bars) == 2
        assert got.bars[1].op == "OR"
        assert got.include_sort is True

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
        slot.path = {"database_name": "main", "expanded": [], "selected": []}
        slot.query = {"bars": [], "sort_by": "path", "ascending": False}
        store.save_slot(slot)
        got = store.get_slot(sid)
        assert got.path["database_name"] == "main"

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


class TestUIPresetColor:
    def test_set_color_updates_only_color(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        p = UIPreset(name="X", color="#000000", window_state={"k": "v"})
        store.save_ui_preset(p)
        assert store.set_ui_preset_color(p.preset_id, "#FF0000") is True
        got = store.get_ui_preset(p.preset_id)
        assert got.color == "#FF0000"
        assert got.window_state == {"k": "v"}

    def test_set_color_missing_returns_false(self, tmp_path):
        store = WorkspaceStore(path=str(tmp_path / "ws.json"))
        assert store.set_ui_preset_color("missing", "#FFFFFF") is False


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
