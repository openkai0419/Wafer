import os
import subprocess
import sys

import pytest

from wafer.core.common.paths import (
    debug_profiles_dir,
    profile_allows_file_write,
    profile_allows_folder,
    profile_config_root,
    profile_data_root,
    resolve_config_path,
    resolve_data_path,
    sample_root,
    scratch_root,
)
from wafer.core.common.profile import (
    PROFILE_ARG,
    PROFILE_PREFIX,
    app_user_model_id,
    current_profile,
    profile_args,
    profile_from_args,
    profile_label,
    validate_profile_name,
)


@pytest.fixture(autouse=True)
def _reset_profile_cache():
    current_profile.cache_clear()
    yield
    current_profile.cache_clear()


def _use_profile(monkeypatch, profile):
    argv = ["main.py"] if profile is None else ["main.py", PROFILE_ARG, profile]
    monkeypatch.setattr(sys, "argv", argv)
    current_profile.cache_clear()


def test_profile_from_args_reads_and_validates():
    assert profile_from_args(["main.py", "--profile", "debug-fm_v2"]) == "debug-fm_v2"
    assert profile_from_args(["main.py", "--viewer"]) is None


def test_profile_from_args_rejects_invalid_and_missing_value():
    with pytest.raises(ValueError):
        profile_from_args(["main.py", "--profile", "main"])
    with pytest.raises(ValueError):
        profile_from_args(["main.py", "--profile"])


@pytest.mark.parametrize("name", ["main", "debug-", "debug-a.b", "debug-a b", "Debug-x", ""])
def test_invalid_profile_names_are_rejected(name):
    with pytest.raises(ValueError) as exc:
        validate_profile_name(name)
    assert repr(name) in str(exc.value) or name in str(exc.value)


def test_valid_profile_name_is_returned_unchanged():
    assert validate_profile_name("debug-A_b-1") == "debug-A_b-1"
    assert PROFILE_PREFIX == "debug-"


def test_profile_args():
    assert profile_args(None) == []
    assert profile_args("debug-x") == [PROFILE_ARG, "debug-x"]


def test_current_profile_is_cached(monkeypatch):
    _use_profile(monkeypatch, "debug-a")
    assert current_profile() == "debug-a"
    monkeypatch.setattr(sys, "argv", ["main.py"])
    assert current_profile() == "debug-a"
    current_profile.cache_clear()
    assert current_profile() is None


def test_roots_follow_profile():
    base = profile_data_root(None)
    debug = profile_data_root("debug-x")
    assert debug.parent == debug_profiles_dir()
    assert debug.name == "debug-x"
    assert debug_profiles_dir().parent == base.parent
    assert debug_profiles_dir().name == base.name + "-debug"
    assert profile_config_root("debug-x").name == "debug-x"
    assert profile_config_root(None).name == base.name
    assert scratch_root("debug-x") == debug / "scratch"


def test_resolve_data_path_uses_profile_root(monkeypatch):
    _use_profile(monkeypatch, "debug-t1")
    assert "/Wafer-debug/debug-t1/" in resolve_data_path("data/x.db")
    assert "/Wafer-debug/debug-t1/" in resolve_config_path("x.ini")


def test_resolve_data_path_without_profile_is_unchanged(monkeypatch):
    _use_profile(monkeypatch, None)
    assert resolve_data_path("data/x.db").endswith("/Wafer/data/x.db")
    assert resolve_config_path("x.ini").endswith("/Wafer/x.ini")


def test_sample_root_env_override_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(tmp_path / "s"))
    assert sample_root() == tmp_path / "s"
    monkeypatch.delenv("WAFER_DEBUG_SAMPLE_ROOT")
    assert sample_root().name == ".sample"


def test_profile_allows_folder_only_inside_sample_or_scratch(monkeypatch, tmp_path):
    sample = tmp_path / "s"
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(sample))
    _use_profile(monkeypatch, "debug-t2")
    scratch = scratch_root("debug-t2")
    assert profile_allows_folder(str(sample))
    assert profile_allows_folder(str(sample / "a" / "b"))
    assert profile_allows_folder(str(scratch / "x"))
    assert not profile_allows_folder(str(tmp_path / "other"))
    assert not profile_allows_folder(str(tmp_path / "s2"))
    _use_profile(monkeypatch, None)
    assert profile_allows_folder(str(tmp_path / "other"))


def test_profile_allows_file_write_only_inside_scratch(monkeypatch, tmp_path):
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(tmp_path / "s"))
    _use_profile(monkeypatch, "debug-t3")
    scratch = scratch_root("debug-t3")
    assert profile_allows_file_write(str(scratch / "out.png"))
    assert not profile_allows_file_write(str(tmp_path / "s" / "a.png"))
    assert not profile_allows_file_write(str(tmp_path / "other.png"))
    _use_profile(monkeypatch, None)
    assert profile_allows_file_write(str(tmp_path / "other.png"))


def test_profile_label():
    assert profile_label(None) == ""
    assert profile_label("debug-x") == "[debug-x] "


def test_app_user_model_id():
    assert app_user_model_id("Wafer.App", None) == "Wafer.App"
    assert app_user_model_id("Wafer.App", "debug-x") == "Wafer.App.debug-x"


@pytest.fixture
def tmp_app_data(monkeypatch, tmp_path):
    import wafer.core.common.paths as paths

    root = str(tmp_path / "appdata")

    class _TmpPlatformDirs:
        def __init__(self, appname=None):
            self.user_data_dir = root
            self.user_config_dir = root

    monkeypatch.setattr(paths, "PlatformDirs", _TmpPlatformDirs)
    return tmp_path / "appdata"


def _make_link(link, target):
    if sys.platform == "win32":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
        if done.returncode != 0:
            pytest.skip("cannot create a junction")
        return
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create a symlink")


def test_profile_allows_path_through_link_into_sample(monkeypatch, tmp_path, tmp_app_data):
    sample = tmp_path / "s"
    sample.mkdir()
    link = tmp_path / "via"
    _make_link(link, sample)
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(sample))
    _use_profile(monkeypatch, "debug-t4")
    assert profile_allows_folder(str(link / "x"))
    assert not profile_allows_file_write(str(link / "x"))


def test_profile_rejects_link_inside_scratch_pointing_elsewhere(monkeypatch, tmp_path, tmp_app_data):
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(tmp_path / "s"))
    _use_profile(monkeypatch, "debug-t5")
    scratch = scratch_root("debug-t5")
    scratch.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = scratch / "escape"
    _make_link(link, outside)
    assert not profile_allows_file_write(str(link / "a.png"))
    assert not profile_allows_folder(str(link))


@pytest.mark.skipif(sys.platform != "win32", reason="case-insensitive file system")
def test_profile_allows_different_case_on_windows(monkeypatch, tmp_path, tmp_app_data):
    sample = tmp_path / "Sample"
    sample.mkdir()
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(sample))
    _use_profile(monkeypatch, "debug-t6")
    assert profile_allows_folder(str(tmp_path / "SAMPLE" / "a"))
    assert not profile_allows_folder(str(tmp_path / "SAMPLE2"))


def test_profile_sibling_with_same_prefix_is_rejected(monkeypatch, tmp_path, tmp_app_data):
    sample = tmp_path / "s"
    sample.mkdir()
    (tmp_path / "s2").mkdir()
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(sample))
    _use_profile(monkeypatch, "debug-t7")
    assert profile_allows_folder(str(sample / "a"))
    assert not profile_allows_folder(str(tmp_path / "s2"))
    assert not profile_allows_folder(str(tmp_path / "s2" / "a"))
