import sys

import pytest

from debug import profile_setup
from debug.mcp_server import DebugSession
from test_support.debug_instances import CHECKOUT, isolate_debug_dirs, wait_until
from wafer.core.common.paths import profile_data_root
from wafer.core.platform.process import AppProcess

pytestmark = [
    pytest.mark.slow,
    pytest.mark.timeout(900),
    pytest.mark.skipif(sys.platform != "win32", reason="runs the real Windows app"),
]

COMMAND_ID = "db.add_database"
NEW_DATABASE = "agent_flow"
CALL_TIMEOUT = 10.0
UI_TIMEOUT = 60.0


@pytest.fixture
def session(tmp_path, monkeypatch):
    isolate_debug_dirs(tmp_path, monkeypatch)
    profile = profile_setup.profile_name_for(CHECKOUT)
    for busy in (profile, profile_setup.TEMPLATE_BUILD_PROFILE):
        if AppProcess.list_profile_processes(busy):
            pytest.skip(f"{busy} is already running; this test does not stop processes it did not start")
    debug = DebugSession()
    try:
        yield debug
    finally:
        try:
            if debug.profile is not None and AppProcess.list_profile_processes(debug.profile):
                debug.stop()
        finally:
            debug.close()
            profile_setup.stop_profile(profile)
            profile_setup.stop_profile(profile_setup.TEMPLATE_BUILD_PROFILE)


def _state(session):
    return session.call("get_state", {}, None, CALL_TIMEOUT)


def test_command_modal_state_flow(session):
    launched = session.launch(str(CHECKOUT))
    assert launched["profile"] == profile_setup.profile_name_for(CHECKOUT)
    before = wait_until(lambda: (state := _state(session)).get("count") and state, UI_TIMEOUT, "the MainWindow to show the sample items")
    assert before["database"] != NEW_DATABASE

    started = session.run_command(COMMAND_ID, None, None)
    assert started["started"] is True
    assert started["modal"] == "Create New"

    modal = session.call("modal_state", {}, None, CALL_TIMEOUT)
    assert modal["title"] == "Create New"
    assert [b["text"] for b in modal["buttons"]] == ["Create", "Cancel"]
    field = modal["fields"][0]["placeholder"]
    session.call("modal_input", {"field": field, "value": NEW_DATABASE}, None, CALL_TIMEOUT)
    assert session.call("modal_state", {}, None, CALL_TIMEOUT)["fields"][0]["text"] == NEW_DATABASE

    clicked = session.call("modal_click", {"text": "Create"}, None, CALL_TIMEOUT)
    assert clicked["deferred"] is True

    wait_until(lambda: session.call("modal_state", {}, None, CALL_TIMEOUT) is None, UI_TIMEOUT, "the Create New dialog to close")
    before_count = before["count"]
    wait_until(lambda: _state(session).get("database") == NEW_DATABASE, UI_TIMEOUT, f"get_state to show the {NEW_DATABASE} database")
    wait_until(lambda: _state(session).get("count") == 0, UI_TIMEOUT, f"the grid to show the empty {NEW_DATABASE} database instead of {before_count} sample items")
    assert (profile_data_root(session.profile) / "dirs" / f"{NEW_DATABASE}.db").is_file()

    profile = session.profile
    assert session.stop() == {"stopped": profile}
    wait_until(lambda: not AppProcess.list_profile_processes(profile), UI_TIMEOUT, f"every process of {profile} to exit")
