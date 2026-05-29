from types import SimpleNamespace

import pytest

from scripts import build, copy_clean_project


def test_release_notes_are_included_in_portable_build_metadata():
    assert "RELEASE_NOTES.md" in build.META_FILES
    assert "CHANGELOG.md" in build.META_FILES


def test_release_notes_are_included_in_clean_project_copy():
    assert "RELEASE_NOTES.md" in copy_clean_project.COPY_FILES
    assert "CHANGELOG.md" in copy_clean_project.COPY_FILES


def test_generate_third_party_notices_uses_utf8_stdio_and_writes_output(tmp_path, monkeypatch):
    seen = {}

    def fake_run(*args, **kwargs):
        seen["args"] = args[0]
        seen["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="notices\n", stderr="")

    monkeypatch.setattr(build.subprocess, "run", fake_run)

    build.generate_third_party_notices(tmp_path)

    assert (tmp_path / "THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8") == "notices\n"
    assert seen["env"]["PYTHONIOENCODING"] == "utf-8"
    assert seen["env"]["PYTHONUTF8"] == "1"
    packages = set(seen["args"][seen["args"].index("--packages") + 1:])
    assert packages == build.RUNTIME_PACKAGES


def test_runtime_packages_cover_root_requirements():
    assert build.ROOT_REQUIREMENT_PACKAGES <= build.RUNTIME_PACKAGES


def test_create_launchers_builds_only_windowed_launcher(tmp_path, monkeypatch):
    commands = []

    monkeypatch.setattr(build, "find_csc", lambda: "csc.exe")
    monkeypatch.setattr(build.subprocess, "run", lambda cmd, check: commands.append(cmd))

    build.create_launchers(tmp_path, "0.0.0")

    assert len(commands) == 1
    command_text = " ".join(str(part) for part in commands[0])
    assert "/target:winexe" in commands[0]
    assert "Wafer.exe" in command_text
    assert "WaferConsole" not in command_text


def test_generate_third_party_notices_raises_on_subprocess_error(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(build.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="boom"):
        build.generate_third_party_notices(tmp_path)