import os
import sys
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytestmark = pytest.mark.setup

EXTENSIONS_ROOT = Path(__file__).resolve().parent.parent.parent / "extensions"

EXTENSIONS_WITH_REQUIREMENTS = [
    "image",
    "animated",
    "video",
    "ffmpeg",
    "ai_tagger",
    "blip_captioner",
]

POST_INSTALL_MAP = {
    "ai_tagger": ("extensions.ai_tagger.collector", "WD14TaggerCollector"),
    "blip_captioner": ("extensions.blip_captioner.collector", "BlipCaptionerCollector"),
    "ffmpeg": ("extensions.ffmpeg.collector", "FfmpegCollectorPlugin"),
    "exiftool": ("extensions.exiftool.collector", "ExifToolCollectorPlugin"),
    "video": ("extensions.video.grid", "VideoGridPlugin"),
}


@dataclass
class InstallEnv:
    base_dir: Path
    extensions_dir: Path
    packages_dir: Path
    stamps_dir: Path
    install_results: dict[str, bool] = field(default_factory=dict)
    post_install_results: dict[str, bool] = field(default_factory=dict)


@pytest.fixture(scope="module")
def install_env(tmp_path_factory) -> InstallEnv:
    base = tmp_path_factory.mktemp("ext_install")
    ext_dir = base / "extensions"
    ext_dir.mkdir()
    pkg_dir = ext_dir / ".packages"
    pkg_dir.mkdir()
    stamps_dir = pkg_dir / ".stamps"
    stamps_dir.mkdir()
    return InstallEnv(
        base_dir=base,
        extensions_dir=ext_dir,
        packages_dir=pkg_dir,
        stamps_dir=stamps_dir,
    )


def _patch_extensions_dir(monkeypatch, install_env: InstallEnv):
    import wafer.plugin.installer as installer

    monkeypatch.setattr(installer, "_extensions_dir_from_plugin", lambda plugin_dir: str(install_env.extensions_dir))


def _copy_requirements(install_env: InstallEnv, ext_name: str):
    real_plugin_dir = EXTENSIONS_ROOT / ext_name
    fake_plugin_dir = install_env.extensions_dir / ext_name
    fake_plugin_dir.mkdir(exist_ok=True)
    req_src = real_plugin_dir / "requirements.txt"
    if req_src.is_file():
        shutil.copy2(str(req_src), str(fake_plugin_dir / "requirements.txt"))


def _ensure_requirements_installed(install_env: InstallEnv, monkeypatch, ext_name: str):
    if install_env.install_results.get(ext_name):
        return
    req_file = EXTENSIONS_ROOT / ext_name / "requirements.txt"
    if not req_file.is_file() or req_file.stat().st_size == 0:
        return
    _patch_extensions_dir(monkeypatch, install_env)
    _copy_requirements(install_env, ext_name)
    from wafer.plugin.installer import install_requirements

    fake_plugin_dir = str(install_env.extensions_dir / ext_name)
    success, _ = install_requirements(fake_plugin_dir, str(install_env.extensions_dir))
    assert success, f"Prerequisites install failed for {ext_name}"
    install_env.install_results[ext_name] = True


def _patch_downloader_paths(monkeypatch, install_env: InstallEnv, ext_name: str):
    lib_base = str(install_env.base_dir / "lib" / ext_name)
    models_base = str(install_env.base_dir / "models" / ext_name)

    if ext_name == "ai_tagger":
        import extensions.ai_tagger._downloader as dl

        monkeypatch.setattr(dl, "_LIB_DIR", lib_base)
        monkeypatch.setattr(dl, "_MODELS_DIR", models_base)

    elif ext_name == "blip_captioner":
        import extensions.blip_captioner._downloader as dl

        monkeypatch.setattr(dl, "_LIB_DIR", lib_base)
        monkeypatch.setattr(dl, "_MODELS_DIR", models_base)

    elif ext_name == "ffmpeg":
        import extensions.ffmpeg._downloader as dl

        monkeypatch.setattr(dl, "_LIB_DIR", lib_base)
        monkeypatch.setattr(dl, "_FFPROBE_PATH", os.path.join(lib_base, "ffprobe.exe"))
        monkeypatch.setattr(dl, "_FFMPEG_PATH", os.path.join(lib_base, "ffmpeg.exe"))
        monkeypatch.setattr(dl, "_7ZR_PATH", os.path.join(lib_base, "7zr.exe"))

    elif ext_name == "exiftool":
        import extensions.exiftool._downloader as dl

        monkeypatch.setattr(dl, "_LIB_DIR", lib_base)
        monkeypatch.setattr(dl, "_EXIFTOOL_PATH", os.path.join(lib_base, "exiftool.exe"))

    elif ext_name == "video":
        import extensions.video._downloader as dl

        monkeypatch.setattr(dl, "_LIB_DIR", lib_base)
        monkeypatch.setattr(dl, "_DLL_PATH", os.path.join(lib_base, "libmpv-2.dll"))
        monkeypatch.setattr(dl, "_7ZR_PATH", os.path.join(lib_base, "7zr.exe"))


def _run_post_install(install_env: InstallEnv, monkeypatch, ext_name: str):
    _ensure_requirements_installed(install_env, monkeypatch, ext_name)
    _patch_extensions_dir(monkeypatch, install_env)
    _patch_downloader_paths(monkeypatch, install_env, ext_name)

    pkg_dir = str(install_env.packages_dir)
    path_added = pkg_dir not in sys.path
    if path_added:
        sys.path.insert(0, pkg_dir)

    try:
        module_path, class_name = POST_INSTALL_MAP[ext_name]
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        fake_plugin_dir = str(install_env.extensions_dir / ext_name)
        cls.post_install(fake_plugin_dir)
        install_env.post_install_results[ext_name] = True
    finally:
        if path_added and pkg_dir in sys.path:
            sys.path.remove(pkg_dir)


class TestSmokeRequirementsInstall:
    @pytest.mark.parametrize("ext_name", EXTENSIONS_WITH_REQUIREMENTS)
    @pytest.mark.timeout(300)
    def test_install_requirements(self, ext_name, install_env, monkeypatch):
        req_file = EXTENSIONS_ROOT / ext_name / "requirements.txt"
        if not req_file.is_file() or req_file.stat().st_size == 0:
            pytest.skip(f"{ext_name} has no/empty requirements.txt")

        _patch_extensions_dir(monkeypatch, install_env)
        _copy_requirements(install_env, ext_name)

        from wafer.plugin.installer import install_requirements

        fake_plugin_dir = str(install_env.extensions_dir / ext_name)
        success, deferred = install_requirements(fake_plugin_dir, str(install_env.extensions_dir))

        assert success, f"install_requirements failed for {ext_name}"

        stamp = install_env.stamps_dir / f"{ext_name}.installed"
        assert stamp.exists(), f"Install stamp not created for {ext_name}"

        pkg_entries = [e for e in install_env.packages_dir.iterdir() if e.name != ".stamps"]
        assert len(pkg_entries) > 0, f"No packages installed for {ext_name}"

        install_env.install_results[ext_name] = True


class TestSmokePostInstall:
    @pytest.mark.timeout(600)
    def test_post_install_ai_tagger(self, install_env, monkeypatch):
        _run_post_install(install_env, monkeypatch, "ai_tagger")

    @pytest.mark.timeout(7200)
    def test_post_install_blip_captioner(self, install_env, monkeypatch):
        _run_post_install(install_env, monkeypatch, "blip_captioner")

    @pytest.mark.timeout(300)
    def test_post_install_ffmpeg(self, install_env, monkeypatch):
        _run_post_install(install_env, monkeypatch, "ffmpeg")

    @pytest.mark.timeout(300)
    def test_post_install_exiftool(self, install_env, monkeypatch):
        _run_post_install(install_env, monkeypatch, "exiftool")

    @pytest.mark.timeout(300)
    def test_post_install_video(self, install_env, monkeypatch):
        _run_post_install(install_env, monkeypatch, "video")
