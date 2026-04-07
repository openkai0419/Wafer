from wafer.core.state import StateStore


class TestStateStoreMultiComponentRoundtrip:
    def test_multiple_components_save_restore(self):
        store = StateStore()
        grid_state = {"base_height": 200, "spacing": 4, "layout_mode": "justified", "scroll_index": 42}
        viewer_state = {"zoom": 1.5, "fit_mode": "width"}
        tree_state = {"expanded": ["/photos", "/art"], "selected": "/photos"}

        store.register("grid", lambda: dict(grid_state), lambda d: None)
        store.register("viewer", lambda: dict(viewer_state), lambda d: None)
        store.register("tree", lambda: dict(tree_state), lambda d: None)

        saved = store.save_all()
        assert set(saved.keys()) == {"grid", "viewer", "tree"}

        restored = {"grid": {}, "viewer": {}, "tree": {}}
        store2 = StateStore()
        store2.register("grid", lambda: {}, lambda d: restored["grid"].update(d))
        store2.register("viewer", lambda: {}, lambda d: restored["viewer"].update(d))
        store2.register("tree", lambda: {}, lambda d: restored["tree"].update(d))

        store2.restore_all(saved)
        assert restored["grid"]["base_height"] == 200
        assert restored["grid"]["layout_mode"] == "justified"
        assert restored["viewer"]["zoom"] == 1.5
        assert restored["tree"]["expanded"] == ["/photos", "/art"]

    def test_partial_restore_with_deferred(self):
        store = StateStore()
        grid_state = {"h": 150}
        store.register("grid", lambda: dict(grid_state), lambda d: None)

        saved = store.save_all()
        saved["panel"] = {"visible": True, "width": 300}

        store2 = StateStore()
        restored_grid = {}
        store2.register("grid", lambda: {}, lambda d: restored_grid.update(d))
        store2.restore_all(saved)
        assert restored_grid["h"] == 150

        restored_panel = {}
        store2.register("panel", lambda: {}, lambda d: restored_panel.update(d))
        assert restored_panel["visible"] is True
        assert restored_panel["width"] == 300

    def test_overwrite_on_second_restore(self):
        store = StateStore()
        captured = {}
        store.register("ns", lambda: {}, lambda d: captured.update(d))

        store.restore_all({"ns": {"version": 1}})
        assert captured["version"] == 1

        store.restore_all({"ns": {"version": 2, "extra": "new"}})
        assert captured["version"] == 2
        assert captured["extra"] == "new"

    def test_unregister_during_lifecycle(self):
        store = StateStore()
        store.register("temp", lambda: {"data": True}, lambda d: None)
        assert "temp" in store.save_all()
        store.unregister("temp")
        assert "temp" not in store.save_all()

    def test_deferred_restore_only_fires_once(self):
        store = StateStore()
        store.restore_all({"late": {"count": 1}})

        call_count = []

        def restore_fn(d):
            call_count.append(d)

        store.register("late", lambda: {}, restore_fn)
        assert len(call_count) == 1

        store.unregister("late")
        store.register("late", lambda: {}, restore_fn)
        assert len(call_count) == 1


class TestStateStoreWithSessionData:
    def test_session_like_save_restore(self):
        from wafer.core.session import QueryState, UIState

        qs = QueryState(database_name="main.db", search_params={"keywords": "test"})
        ui = UIState(window_state={"geometry": "geo"}, component_states={"grid": {"h": 200}})

        store = StateStore()
        store.register("query", lambda: qs.to_dict(), lambda d: None)
        store.register("ui", lambda: ui.to_dict(), lambda d: None)

        saved = store.save_all()

        store2 = StateStore()
        restored_q = {}
        restored_u = {}
        store2.register("query", lambda: {}, lambda d: restored_q.update(d))
        store2.register("ui", lambda: {}, lambda d: restored_u.update(d))
        store2.restore_all(saved)

        qs2 = QueryState.from_dict(restored_q)
        assert qs2.database_name == "main.db"
        assert qs2.search_params["keywords"] == "test"

        ui2 = UIState.from_dict(restored_u)
        assert ui2.window_state["geometry"] == "geo"
        assert ui2.component_states["grid"]["h"] == 200
