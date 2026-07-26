import pytest
from unittest.mock import MagicMock

from PySide6 import QtCore, QtGui, QtWidgets
from wafer.ui.panel.searchable_meta_widget import (
    SearchKvDetailDialog,
    SearchableMetaWidget,
    build_value_html,
    highlight_html,
    SHORT_VALUE_LIMIT,
    SNIPPET_BUDGET,
    SAFETY_CHAR_LIMIT,
)
from wafer.ui.panel.tag_edit_service import TagEditService


@pytest.fixture(autouse=True)
def reset_tag_edit_service():
    TagEditService._instance = None
    yield
    inst = TagEditService._instance
    if inst is not None and inst._timeout_timer is not None:
        inst._timeout_timer.stop()
    TagEditService._instance = None


def _menu_action_label(action):
    widget = action.defaultWidget() if isinstance(action, QtWidgets.QWidgetAction) else None
    if widget is not None:
        labels = [label.text() for label in widget.findChildren(QtWidgets.QLabel) if label.objectName() != "checkMark" and label.text()]
        if labels:
            return labels[0]
    return action.text()


def _menu_labels(menu):
    labels = []
    for action in menu.actions():
        if action.isSeparator():
            continue
        text = _menu_action_label(action)
        if text:
            labels.append(text)
        if action.menu():
            labels.extend(_menu_labels(action.menu()))
    return labels


def _find_menu_action(menu, text):
    for action in menu.actions():
        if _menu_action_label(action) == text:
            return action
        if action.menu():
            found = _find_menu_action(action.menu(), text)
            if found is not None:
                return found
    return None


def test_set_data_populates_grid(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1", "b": "2"})
    assert w._data == {"a": "1", "b": "2"}
    assert len(w._filtered_keys) == 2


def test_filter_by_key(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("width")
    assert w._filtered_keys == ["width"]


def test_filter_by_value(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("canon")
    assert w._filtered_keys == ["model"]


def test_filter_empty_shows_all(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    data = {"a": "1", "b": "2", "c": "3"}
    w.set_data(data)
    w._apply_filter("")
    assert set(w._filtered_keys) == set(data.keys())


def test_status_label_hidden_when_no_filter(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1", "b": "2"})
    w._apply_filter("")
    assert w._status_label.isHidden()


def test_status_label_visible_when_filtered(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("width")
    assert not w._status_label.isHidden()
    assert "1 / 3" in w._status_label.text()


def test_current_query(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w._search.setText("  Hello  ")
    assert w.current_query() == "hello"


def test_build_value_html_short_no_query():
    result = build_value_html("hello", "", None)
    assert "hello" in result
    assert "…" not in result


def test_build_value_html_long_no_query():
    long_text = "a" * (SHORT_VALUE_LIMIT + 500)
    result = build_value_html(long_text, "", None)
    assert "…" in result
    assert len(result) < len(long_text)


def test_build_value_html_long_with_match():
    prefix = "x" * 600
    suffix = "y" * 600
    text = prefix + "FINDME" + suffix
    result = build_value_html(text, "findme")
    assert "<span" in result
    assert "FINDME" in result


def test_build_value_html_snippet_budget_distribution():
    parts = []
    for i in range(10):
        parts.append("a" * 100 + f"MATCH{i}" + "b" * 100)
    text = "z".join(parts)
    result = build_value_html(text, "match")
    assert "<span" in result
    assert "<br>" in result


def test_build_value_html_remaining_shown():
    parts = []
    for i in range(30):
        parts.append("a" * 200 + f"HIT{i}" + "b" * 200)
    text = "z".join(parts)
    result = build_value_html(text, "hit")
    assert "more found" in result


def test_highlight_html_no_query():
    result = highlight_html("hello world", "")
    assert "<span" not in result
    assert "hello world" in result


def test_highlight_html_with_query():
    result = highlight_html("hello world", "world")
    assert "<span" in result


def test_highlight_html_escapes_html():
    result = highlight_html("<b>bold</b>", "")
    assert "<b>" not in result
    assert "&lt;b&gt;" in result


def test_highlight_html_case_insensitive():
    result = highlight_html("Hello HELLO hello", "hello")
    assert result.count("<span") == 3


def test_highlight_html_newlines_to_br():
    result = highlight_html("line1\nline2", "")
    assert "<br>" in result


def test_model_row_count_matches_filter(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1", "b": "2", "c": "3"})
    w._apply_filter("a")
    assert w._model.rowCount() == 1
    w._apply_filter("")
    assert w._model.rowCount() == 3


def test_safety_limit_truncates(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    huge = "a" * (SAFETY_CHAR_LIMIT + 500)
    w.set_data({"big": huge})
    assert len(w._filtered_keys) == 1


def test_search_index_none_before_async_build(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1"})
    assert w._search_index is None or isinstance(w._search_index, dict)



def test_search_index_built_after_async(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200"})
    qtbot.waitUntil(lambda: w._search_index is not None, timeout=5000)
    assert "width" in w._search_index
    assert w._search_index["width"] == "100"
    assert w._search_index["height"] == "200"



def test_filter_uses_index_when_available(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    qtbot.waitUntil(lambda: w._search_index is not None, timeout=5000)
    w._apply_filter("canon")
    assert w._filtered_keys == ["model"]



def test_filter_works_without_index(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w._data = {"width": "100", "height": "200", "model": "Canon"}
    w._search_index = None
    w._apply_filter("canon")
    assert w._filtered_keys == ["model"]


def test_set_data_cancels_previous_index_build(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"old": "data"})
    w.set_data({"new": "data"})
    qtbot.waitUntil(lambda: w._search_index is not None, timeout=5000)
    assert "new" in w._search_index
    assert "old" not in w._search_index



def test_debounce_attribute_exists(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    assert w.DEBOUNCE_MS == 50


def test_full_value_returns_untruncated(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    huge = "x" * (SHORT_VALUE_LIMIT + 5000)
    w.set_data({"big": huge})
    assert w._full_value("big") == huge
    assert len(w._full_value("big")) == SHORT_VALUE_LIMIT + 5000


def test_key_for_row_returns_filtered_key(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1", "b": "2", "c": "3"})
    w._apply_filter("b")
    assert w._key_for_row(0) == "b"
    assert w._key_for_row(1) is None
    assert w._key_for_row(-1) is None


def test_double_click_opens_edit_dialog(qtbot, monkeypatch):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    huge = "y" * (SHORT_VALUE_LIMIT + 1000)
    w.set_data({"big": huge})
    captured = {}

    class _Dialog:
        def __init__(self, parent, **kwargs):
            captured.update(kwargs)
            self.delete_requested = MagicMock()

        def exec(self):
            return QtWidgets.QDialog.Rejected

    import wafer.ui.panel.searchable_meta_widget as mod

    monkeypatch.setattr(mod, "SearchKvDetailDialog", _Dialog)
    index = w._model.index(0, 0)
    w._on_double_clicked(index)
    assert captured["key"] == "big"
    assert captured["value"] == huge


def test_context_menu_copy_value_uses_full_text(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    huge = "z" * (SHORT_VALUE_LIMIT + 500)
    w.set_data({"big": huge})

    QtWidgets.QApplication.clipboard().clear()
    menu = w._build_context_menu(0, "big", "big", huge)
    labels = _menu_labels(menu)
    assert any("key" in a.lower() for a in labels)
    assert any("row" in a.lower() for a in labels)
    assert any("edit" in a.lower() for a in labels)
    copy_value = _find_menu_action(menu, "Copy value")
    assert copy_value is not None
    copy_value.trigger()
    assert QtWidgets.QApplication.clipboard().text() == huge


def test_submit_upsert_uses_tag_context(qtbot, monkeypatch):
    svc = TagEditService.instance()
    node = MagicMock()
    monkeypatch.setattr(svc, "_resolve_node", lambda: node)
    w = SearchableMetaWidget(scope="tag")
    qtbot.addWidget(w)
    w.set_context({"rating": "old"}, {"rating": False}, path="/a.png", file_hash="h1", db="db", scope="tag")
    w._submit_save("rating", "rating", "new", True)
    payload = node.send_reliable.call_args[0][1]
    assert payload["scope"] == "tag"
    assert payload["upserts"] == [{"key": "rating", "value": "new", "locked": True}]


def test_submit_rename_uses_prefixed_meta_key(qtbot, monkeypatch):
    svc = TagEditService.instance()
    node = MagicMock()
    monkeypatch.setattr(svc, "_resolve_node", lambda: node)
    w = SearchableMetaWidget(scope="meta_info", prefix="exiftool")
    qtbot.addWidget(w)
    w.set_context({"width": "100"}, {"width": False}, path="/a.png", db="db", scope="meta_info", prefix="exiftool")
    w._submit_save("width", "image_width", "100", False)
    payload = node.send_reliable.call_args[0][1]
    assert payload["scope"] == "meta_info"
    assert payload["renames"] == [{"old": "exiftool.width", "new": "exiftool.image_width", "value": "100", "locked": False}]


def test_delete_uses_full_key(qtbot, monkeypatch):
    svc = TagEditService.instance()
    node = MagicMock()
    monkeypatch.setattr(svc, "_resolve_node", lambda: node)
    w = SearchableMetaWidget(scope="meta_info", prefix="custom")
    qtbot.addWidget(w)
    w.set_context({"k": "v"}, {}, path="/a.png", db="db", scope="meta_info", prefix="custom")
    w._submit_delete("k")
    payload = node.send_reliable.call_args[0][1]
    assert payload["deletes"] == ["custom.k"]


def test_detail_dialog_places_lock_and_delete_in_bottom_action_row(qtbot):
    dlg = SearchKvDetailDialog(None, title="Edit", key="k", value="v", locked=True)
    qtbot.addWidget(dlg)
    button_layout = dlg.layout().itemAt(dlg.layout().count() - 1).widget().layout()
    assert button_layout.itemAt(0).widget() is dlg.delete_btn
    assert button_layout.itemAt(1).widget() is dlg.lock_check
    assert button_layout.itemAt(2).spacerItem() is not None
    assert button_layout.itemAt(3).widget() is dlg.revert_btn
    assert button_layout.itemAt(4).widget() is dlg.save_btn
    assert button_layout.itemAt(5).widget() is dlg.cancel_btn


def test_detail_dialog_hides_delete_in_add_mode(qtbot):
    dlg = SearchKvDetailDialog(None, title="Add", add_mode=True)
    qtbot.addWidget(dlg)
    button_layout = dlg.layout().itemAt(dlg.layout().count() - 1).widget().layout()
    assert button_layout.itemAt(0).widget() is dlg.delete_btn
    assert button_layout.itemAt(1).widget() is dlg.lock_check
    assert dlg.delete_btn.isHidden()


def test_detail_dialog_delete_emits_signal_without_closing(qtbot):
    dlg = SearchKvDetailDialog(None, title="Edit", key="rating", value="v")
    qtbot.addWidget(dlg)

    emitted = []
    dlg.delete_requested.connect(lambda: emitted.append(True))
    dlg.delete_btn.click()

    assert emitted == [True]
    assert dlg.result() == QtWidgets.QDialog.DialogCode.Rejected


def test_lock_icon_draws_only_locked_rows(qtbot, monkeypatch):
    import wafer.ui.panel.searchable_meta_widget as mod

    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"locked": "1", "open": "2"}, {"locked": True, "open": False})
    calls = []
    monkeypatch.setattr(mod, "icon_draw", lambda *args: calls.append(args))

    rect = QtCore.QRectF(0, 0, 18, 20)
    w._delegate._draw_lock_icon(None, rect, w._model.index(0, 0))
    w._delegate._draw_lock_icon(None, rect, w._model.index(1, 0))

    assert len(calls) == 1
    assert calls[0][0] == "lock"
    assert calls[0][3] == QtGui.QColor(mod.ThemeManager.instance().palette.warning)


def test_context_menu_lock_label_reflects_state(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1", "b": "2"}, {"a": True, "b": False})
    assert _find_menu_action(w._build_context_menu(0, "a", "a", "1"), "Unlock") is not None
    assert _find_menu_action(w._build_context_menu(1, "b", "b", "2"), "Lock") is not None
    assert _find_menu_action(w._build_context_menu(0, "a", "a", "1"), "Delete…") is not None


def test_toggle_lock_submits_inverted_lock(qtbot, monkeypatch):
    svc = TagEditService.instance()
    node = MagicMock()
    monkeypatch.setattr(svc, "_resolve_node", lambda: node)
    w = SearchableMetaWidget(scope="meta_info", prefix="custom")
    qtbot.addWidget(w)
    w.set_context({"k": "v"}, {"k": False}, path="/a.png", db="db", scope="meta_info", prefix="custom")
    w._toggle_lock("k")
    payload = node.send_reliable.call_args[0][1]
    assert payload["upserts"] == [{"key": "custom.k", "value": "v", "locked": True}]
    assert payload["lock_only"] is True


def test_delete_request_this_only(qtbot, monkeypatch):
    import wafer.ui.panel.searchable_meta_widget as mod

    monkeypatch.setattr(mod.ConfirmDialog, "ask", staticmethod(lambda *a, **k: k["buttons"][0]))
    w = SearchableMetaWidget(scope="meta_info", prefix="custom")
    qtbot.addWidget(w)
    w.set_context({"k": "v"}, {}, path="/a.png", db="db", scope="meta_info", prefix="custom")
    single = MagicMock()
    everywhere = MagicMock()
    monkeypatch.setattr(w, "_submit_delete", single)
    monkeypatch.setattr(w, "_delete_key_everywhere", everywhere)
    w._confirm_delete("k")
    single.assert_called_once_with("k")
    everywhere.assert_not_called()


def test_delete_request_all_dbs(qtbot, monkeypatch):
    import wafer.ui.panel.searchable_meta_widget as mod

    captured = {}

    def fake_ask(*a, **k):
        captured["disabled"] = k.get("disabled")
        return k["buttons"][1]

    monkeypatch.setattr(mod.ConfirmDialog, "ask", staticmethod(fake_ask))
    w = SearchableMetaWidget(scope="meta_info", prefix="custom")
    qtbot.addWidget(w)
    w.set_context({"k": "v"}, {}, path="/a.png", db="db", scope="meta_info", prefix="custom")
    everywhere = MagicMock()
    monkeypatch.setattr(w, "_delete_key_everywhere", everywhere)
    w._confirm_delete("k")
    everywhere.assert_called_once_with("k")
    assert captured["disabled"] == ()


def test_delete_request_disables_all_dbs_when_no_prefix(qtbot, monkeypatch):
    import wafer.ui.panel.searchable_meta_widget as mod

    captured = {}

    def fake_ask(*a, **k):
        captured["disabled"] = k.get("disabled")
        captured["buttons"] = k["buttons"]
        return k["buttons"][2]

    monkeypatch.setattr(mod.ConfirmDialog, "ask", staticmethod(fake_ask))
    w = SearchableMetaWidget(scope="tag", prefix="")
    qtbot.addWidget(w)
    w.set_data({"k": "v"})
    w._confirm_delete("k")
    assert captured["disabled"] == (captured["buttons"][1],)


def test_delete_key_everywhere_deletes_and_disables(qtbot, monkeypatch):
    import wafer.ui.panel.searchable_meta_widget as mod

    monkeypatch.setattr(mod, "list_setting_db_names", lambda: ["db1", "db2"])
    delete_calls = []
    state_calls = []
    monkeypatch.setattr(mod.KeyFilter, "send_delete_keys", staticmethod(lambda dbs, keys, prefix, *, re_collect: delete_calls.append((list(dbs), list(keys), prefix, re_collect))))
    monkeypatch.setattr(mod.KeyFilter, "apply_key_states", classmethod(lambda cls, prefix, states: state_calls.append((prefix, states))))
    w = SearchableMetaWidget(scope="meta_info", prefix="custom")
    qtbot.addWidget(w)
    w.set_context({"k": "v"}, {}, path="/a.png", db="db", scope="meta_info", prefix="custom")
    w._delete_key_everywhere("k")
    assert delete_calls == [(["db1", "db2"], ["custom.k"], "custom", False)]
    assert state_calls == [("custom", {"k": False})]


def test_delete_key_everywhere_noop_without_prefix(qtbot, monkeypatch):
    import wafer.ui.panel.searchable_meta_widget as mod

    monkeypatch.setattr(mod, "list_setting_db_names", lambda: ["db1"])
    called = []
    monkeypatch.setattr(mod.KeyFilter, "send_delete_keys", staticmethod(lambda *a, **k: called.append(a)))
    w = SearchableMetaWidget(scope="tag", prefix="")
    qtbot.addWidget(w)
    w.set_data({"k": "v"})
    w._delete_key_everywhere("k")
    assert called == []
