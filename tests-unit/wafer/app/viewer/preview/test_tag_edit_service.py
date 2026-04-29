from unittest.mock import MagicMock

import pytest

from wafer.app.viewer.preview.tag_edit_service import TagEditService, PendingEdit


@pytest.fixture
def service(qtbot, monkeypatch):
    TagEditService._instance = None
    svc = TagEditService.instance()
    node = MagicMock()
    node.send_reliable = MagicMock(return_value=None)
    monkeypatch.setattr(svc, "_resolve_node", lambda: node)
    yield svc, node
    TagEditService._instance = None


def _submit(svc, upserts=None, deletes=None, *, file_hash="h1", lock_only=False, renames=None):
    return svc.submit(
        ["p"],
        list(upserts or []),
        list(deletes or []),
        "db",
        lock_only=lock_only,
        renames=renames,
        file_hash=file_hash,
    )


def _ack(rid, applied_keys=None, deleted_keys=None, file_hash="h1"):
    return {
        "request_id": rid,
        "scope": "tag",
        "paths": ["p"],
        "applied": {"p": list(applied_keys or [])},
        "deleted": {"p": list(deleted_keys or [])},
        "targets": {"p": file_hash} if file_hash else {},
    }


def _pending_key(file_hash="h1", key="k", scope="tag"):
    return (scope, file_hash, key)


def test_submit_caches_pending_and_emits_overlay(service, qtbot):
    svc, node = service
    received = []
    svc.kv_overlay_changed.connect(lambda scope, target: received.append((scope, target)))
    rid = _submit(svc, upserts=[("k", "v", False)])
    assert rid is not None
    node.send_reliable.assert_called_once()
    assert _pending_key() in svc._pending
    assert received == [("tag", "h1")]


def test_submit_without_file_hash_skips_pending(service):
    svc, node = service
    rid = svc.submit(["p1", "p2"], [("k", "v", False)], [], "db")
    assert rid is not None
    node.send_reliable.assert_called_once()
    assert svc._pending == {}


def test_handle_ack_clears_only_matching_request_id(service):
    svc, node = service
    rid_a = _submit(svc, upserts=[("k", "vA", False)])
    rid_b = _submit(svc, upserts=[("k", "vB", False)])
    assert svc._pending[_pending_key()].request_id == rid_b
    svc.handle_ack(_ack(rid_a, applied_keys=["k"]))
    assert _pending_key() in svc._pending
    assert svc._pending[_pending_key()].request_id == rid_b
    svc.handle_ack(_ack(rid_b, applied_keys=["k"]))
    assert _pending_key() not in svc._pending


def test_handle_ack_emits_commit_confirmed_with_committed(service):
    svc, _ = service
    received = []
    svc.kv_commit_confirmed.connect(lambda scope, target, applied, deleted: received.append((scope, target, dict(applied), list(deleted))))
    rid = _submit(svc, upserts=[("k", "v", True)], deletes=["d"])
    svc.handle_ack(_ack(rid, applied_keys=["k"], deleted_keys=["d"]))
    assert received == [("tag", "h1", {"k": ("v", True)}, ["d"])]


def test_apply_overlay_returns_pending_edits(service):
    svc, _ = service
    _submit(svc, upserts=[("new", "x", False)])
    _submit(svc, deletes=["old"])
    tags, locks, states = svc.apply_overlay("h1", {"old": "y", "stable": "s"}, {"old": False, "stable": False})
    assert tags == {"new": "x", "stable": "s"}
    assert states["new"] == "saving"
    assert states["old"] == "deleting"


def test_check_timeouts_safe_during_iteration(service, monkeypatch):
    svc, _ = service
    _submit(svc, upserts=[("k", "v", False)])
    pending = svc._pending[_pending_key()]
    pending.sent_at = 0.0
    received = []
    svc.kv_overlay_changed.connect(lambda scope, target: received.append((scope, target)))
    svc._check_timeouts()
    assert pending.failed is True


def test_lock_only_flag_passed_in_payload(service):
    svc, node = service
    _submit(svc, upserts=[("k", "v", True)], lock_only=True)
    args, kwargs = node.send_reliable.call_args
    assert kwargs["dst"] == "indexer"
    payload = args[1]
    assert payload["lock_only"] is True
    assert payload["paths"] == ["p"]


def test_handle_ack_ignores_unknown_request_id(service):
    svc, _ = service
    _submit(svc, upserts=[("k", "v", False)])
    svc.handle_ack(_ack("ghost", applied_keys=[], deleted_keys=[]))
    assert _pending_key() in svc._pending


def test_submit_short_circuits_when_no_payload(service):
    svc, node = service
    assert _submit(svc) is None
    node.send_reliable.assert_not_called()
