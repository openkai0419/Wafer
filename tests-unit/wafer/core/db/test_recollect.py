from unittest.mock import MagicMock

from wafer.core.commands.binding.instance_registry import InstanceRegistry
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
        {"mode": "reset", "collector": "exif", "sources": ["/a.png"], "prefixes": None},
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


def test_forget_all_payload(monkeypatch):
    node = _node(monkeypatch)
    Recollect.forget(db_scope=["db1"], all=True)
    node.send_reliable.assert_called_once_with(
        "recollect",
        {"mode": "forget", "sources": None, "prefixes": None, "all": True},
        dst="indexer",
        db="db1",
    )


def test_purge_payload(monkeypatch):
    node = _node(monkeypatch)
    Recollect.purge(db_scope=["db1"], collector="color", keys=["k"], delete=False, re_collect=True)
    node.send_reliable.assert_called_once_with(
        "recollect",
        {"mode": "purge", "collector": "color", "keys": ["k"], "delete": False, "re_collect": True},
        dst="indexer",
        db="db1",
    )


def test_no_node_returns_zero(monkeypatch):
    monkeypatch.setattr(InstanceRegistry.instance(), "resolve_node", lambda: None)
    assert Recollect.reset(db_scope=["db1"]) == 0
