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


def test_submit_caches_pending_and_emits_overlay(service, qtbot):
    svc, node = service
    received = []
    svc.overlay_changed.connect(received.append)
    rid = svc.submit("p", "h1", [("k", "v", False)], [], "db")
    assert rid is not None
    node.send_reliable.assert_called_once()
    assert ("h1", "k") in svc._pending
    assert received == ["h1"]


def test_handle_ack_clears_only_matching_request_id(service):
    svc, node = service
    rid_a = svc.submit("p", "h1", [("k", "vA", False)], [], "db")
    pending_a = svc._pending[("h1", "k")]
    rid_b = svc.submit("p", "h1", [("k", "vB", False)], [], "db")
    assert svc._pending[("h1", "k")].request_id == rid_b
    svc.handle_ack({"request_id": rid_a, "applied": ["k"], "deleted": []})
    assert ("h1", "k") in svc._pending
    assert svc._pending[("h1", "k")].request_id == rid_b
    svc.handle_ack({"request_id": rid_b, "applied": ["k"], "deleted": []})
    assert ("h1", "k") not in svc._pending


def test_handle_ack_emits_commit_confirmed_with_committed(service):
    svc, _ = service
    received = []
    svc.commit_confirmed.connect(lambda fh, applied, deleted: received.append((fh, dict(applied), list(deleted))))
    rid = svc.submit("p", "h1", [("k", "v", True)], ["d"], "db")
    svc.handle_ack({"request_id": rid, "file_hash": "h1", "applied": ["k"], "deleted": ["d"]})
    assert received == [("h1", {"k": ("v", True)}, ["d"])]


def test_apply_overlay_returns_pending_edits(service):
    svc, _ = service
    svc.submit("p", "h1", [("new", "x", False)], [], "db")
    svc.submit("p", "h1", [], ["old"], "db")
    tags, locks, states = svc.apply_overlay("h1", {"old": "y", "stable": "s"}, {"old": False, "stable": False})
    assert tags == {"new": "x", "stable": "s"}
    assert states["new"] == "saving"
    assert states["old"] == "deleting"


def test_check_timeouts_safe_during_iteration(service, monkeypatch):
    svc, _ = service
    rid = svc.submit("p", "h1", [("k", "v", False)], [], "db")
    pending = svc._pending[("h1", "k")]
    pending.sent_at = 0.0
    received = []
    svc.overlay_changed.connect(received.append)
    svc._check_timeouts()
    assert pending.failed is True


def test_lock_only_flag_passed_in_payload(service):
    svc, node = service
    svc.submit("p", "h1", [("k", "v", True)], [], "db", lock_only=True)
    args, kwargs = node.send_reliable.call_args
    assert kwargs["dst"] == "indexer"
    payload = args[1]
    assert payload["lock_only"] is True


def test_handle_ack_ignores_unknown_request_id(service):
    svc, _ = service
    svc.submit("p", "h1", [("k", "v", False)], [], "db")
    svc.handle_ack({"request_id": "ghost", "applied": [], "deleted": []})
    assert ("h1", "k") in svc._pending


def test_submit_short_circuits_when_no_payload(service):
    svc, node = service
    assert svc.submit("p", "h1", [], [], "db") is None
    node.send_reliable.assert_not_called()
