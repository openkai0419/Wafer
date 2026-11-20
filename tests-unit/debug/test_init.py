import os
import subprocess
import sys
from pathlib import Path

import pytest

import debug

ROOT = Path(debug.__file__).resolve().parent.parent
LOG_NAMES = sorted(f"viewer_{i}.log" for i in range(8))


def run_tool(tmp_path, module, profile_args, command=("launch",)):
    appdata = tmp_path / "appdata"
    logs = appdata / "Wafer" / ".log"
    logs.mkdir(parents=True)
    for name in LOG_NAMES:
        (logs / name).write_text("x", encoding="utf-8")
    env = {**os.environ, "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(appdata), "WIN_PD_OVERRIDE_APPDATA": str(appdata)}
    done = subprocess.run([sys.executable, "-m", module, *profile_args, *command], cwd=ROOT, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=25)
    return appdata, done


def test_tools_accept_the_tooling_profile_in_another_case(tmp_path):
    appdata, done = run_tool(tmp_path, "debug.profile_setup", ["--profile", "debug-Tools"], ("stop", "debug-no-such-profile"))

    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in (appdata / "Wafer").rglob("*")) == [".log", *LOG_NAMES]


@pytest.mark.parametrize("module", ["debug.profile_setup", "debug.mcp_server"])
@pytest.mark.parametrize(
    ("profile_args", "reason"),
    [([], "--profile debug-tools"), (["--profile", "debug-main"], "--profile debug-tools"), (["--profile", "nope"], "Invalid profile name 'nope'")],
    ids=["none", "other-profile", "invalid"],
)
def test_tools_without_the_tooling_profile_never_touch_the_normal_data_folder(tmp_path, module, profile_args, reason):
    appdata, done = run_tool(tmp_path, module, profile_args)

    assert done.returncode != 0
    assert reason in done.stderr
    assert sorted(p.name for p in (appdata / "Wafer").rglob("*")) == [".log", *LOG_NAMES]
    assert not (appdata / "Wafer-debug").exists()
