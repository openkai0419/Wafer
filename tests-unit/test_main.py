import os
import subprocess
import sys
from pathlib import Path

import pytest

MAIN = Path(__file__).resolve().parents[1] / "main.py"

ROLE_ARGS = [
    [],
    ["--tray"],
    ["--viewer"],
    ["--webui"],
    ["--indexer", "sample"],
    ["--collector", "sample", "--plugin", "color"],
    ["--parser", "sample", "--plugin", "exif"],
]


@pytest.mark.parametrize("role_args", ROLE_ARGS, ids=lambda args: " ".join(args) or "root")
@pytest.mark.parametrize("profile_first", [True, False], ids=["profile-first", "profile-last"])
def test_parser_accepts_the_profile_with_every_role(role_args, profile_first):
    from main import build_parser

    profile = ["--profile", "debug-x"]
    argv = profile + role_args if profile_first else role_args + profile
    args = build_parser().parse_args(argv)

    assert args.profile == "debug-x"


def test_parser_leaves_the_profile_unset_without_the_option():
    from main import build_parser

    assert build_parser().parse_args(["--tray"]).profile is None


def test_parser_rejects_a_non_debug_profile(capsys):
    from main import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--profile", "release", "--tray"])
    assert "--profile" in capsys.readouterr().err


def test_parser_reads_the_equals_form_like_the_runtime():
    from main import build_parser
    from wafer.core.common.profile import profile_from_args

    argv = ["--tray", "--profile=debug-x"]
    assert build_parser().parse_args(argv).profile == "debug-x"
    assert profile_from_args(["main.py", *argv]) == "debug-x"


@pytest.mark.parametrize("argv", [["--prof", "debug-x", "--tray"], ["--tra", "--profile", "debug-x"]])
def test_parser_rejects_abbreviated_options(argv, capsys):
    from main import build_parser

    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(argv)
    assert exc.value.code != 0
    assert "unrecognized arguments" in capsys.readouterr().err


def test_a_repeated_profile_stops_the_process_before_it_starts(tmp_path):
    env = {**os.environ, "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(tmp_path)}
    done = subprocess.run(
        [sys.executable, str(MAIN), "--profile", "debug-x", "--profile", "debug-y", "--version"],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert done.returncode != 0
    assert "--profile was given more than once" in done.stderr
    assert "Wafer " not in done.stdout


def _run_main(monkeypatch, argv, runtime_profile):
    import main

    errors = []
    started = []
    monkeypatch.setattr(sys, "argv", ["main.py", *argv])
    monkeypatch.setattr(main, "current_profile", lambda: runtime_profile)
    monkeypatch.setattr(main.AppLogger, "error", lambda message, *args, **kwargs: errors.append(message))
    monkeypatch.setattr(main, "_entry_tray", lambda: started.append("tray"))
    return main, errors, started


def test_main_refuses_to_start_when_parser_and_runtime_disagree(monkeypatch):
    main, errors, started = _run_main(monkeypatch, ["--tray", "--profile", "debug-x"], None)

    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code != 0
    assert started == []
    assert len(errors) == 1 and "debug-x" in errors[0] and "--profile" in errors[0]


def test_main_starts_when_parser_and_runtime_agree(monkeypatch):
    main, errors, started = _run_main(monkeypatch, ["--tray", "--profile=debug-x"], "debug-x")

    main.main()
    assert started == ["tray"]
    assert errors == []


def test_main_refuses_a_profile_when_the_debug_tools_are_not_shipped(monkeypatch, tmp_path):
    main, errors, started = _run_main(monkeypatch, ["--tray", "--profile", "debug-x"], "debug-x")
    monkeypatch.setattr(main, "get_app_root_dir", lambda: tmp_path)

    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code != 0
    assert started == []
    assert len(errors) == 1 and "debug-x" in errors[0] and str(tmp_path / "debug") in errors[0]


def test_main_starts_without_a_profile_when_the_debug_tools_are_not_shipped(monkeypatch, tmp_path):
    main, errors, started = _run_main(monkeypatch, ["--tray"], None)
    monkeypatch.setattr(main, "get_app_root_dir", lambda: tmp_path)

    main.main()
    assert started == ["tray"]
    assert errors == []
