from wafer.core.db import dispatch


class _Node:
    def __init__(self):
        self.sent = []

    def send_reliable(self, topic, payload, *, dst, db):
        self.sent.append(("reliable", topic, payload, dst, db))

    def send(self, topic, payload, *, dst, db):
        self.sent.append(("plain", topic, payload, dst, db))


def test_resolve_db_scope_all_uses_data_names(monkeypatch):
    monkeypatch.setattr(dispatch, "list_data_db_names", lambda: ["a", "b"])
    assert dispatch.resolve_db_scope("*") == ["a", "b"]


def test_send_to_db_scope_reliable(monkeypatch):
    monkeypatch.setattr(dispatch, "list_data_db_names", lambda: ["a", "b"])
    node = _Node()
    sent = dispatch.send_to_db_scope(node, "topic", {"x": 1}, db_scope="*")
    assert sent == 2
    assert node.sent == [
        ("reliable", "topic", {"x": 1}, "indexer", "a"),
        ("reliable", "topic", {"x": 1}, "indexer", "b"),
    ]


def test_send_to_db_scope_specific_plain():
    node = _Node()
    sent = dispatch.send_to_db_scope(node, "topic", {"x": 1}, db_scope="one", reliable=False)
    assert sent == 1
    assert node.sent == [("plain", "topic", {"x": 1}, "indexer", "one")]