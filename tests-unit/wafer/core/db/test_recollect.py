from unittest.mock import MagicMock

from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.core.db.recollect import Recollect


def _node(monkeypatch):
    node = MagicMock()
    monkeypatch.setattr(InstanceRegistry.instance(), "resolve_node", lambda: node)
    return node


def test_reset_payload(monkeypatch):
    node = _node(monkeypatch)
    Recollect.reset(db_scope=["db1"], collector="exif", sources=["/a.png"])
    node.send_reliable.assert_called_once_with(
        "recollect",
        {"mode": "reset", "collector": "exif", "sources": ["/a.png"], "prefixes": None, "keys": None, "delete": False, "re_collect": True},
        dst="indexer",
        db="db1",
    )


def test_forget_payload(monkeypatch):
    node = _node(monkeypatch)
    Recollect.forget(db_scope=["db1"], prefixes=["/dir"])
    node.send_reliable.assert_called_once_with(
        "recollect",
        {"mode": "forget", "sources": None, "prefixes": ["/dir"], "all": False},
        dst="indexer",
        db="db1",
    )


def test_no_node_returns_zero(monkeypatch):
    monkeypatch.setattr(InstanceRegistry.instance(), "resolve_node", lambda: None)
    assert Recollect.reset(db_scope=["db1"]) == 0
