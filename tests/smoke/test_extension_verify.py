import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.setup

EXTENSIONS_ROOT = Path(__file__).resolve().parent.parent.parent / "extensions"


def _add_packages_to_path():
    pkg_dir = str(EXTENSIONS_ROOT / ".packages")
    if os.path.isdir(pkg_dir) and pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)
        return pkg_dir
    return None


def _skip_unless_installed(ext_name: str):
    stamps_dir = EXTENSIONS_ROOT / ".packages" / ".stamps"
    if not (stamps_dir / f"{ext_name}.installed").exists():
        pytest.skip(f"{ext_name} not installed (no .installed stamp)")


def _skip_unless_post_installed(ext_name: str):
    stamps_dir = EXTENSIONS_ROOT / ".packages" / ".stamps"
    if not (stamps_dir / f"{ext_name}.post_installed").exists():
        pytest.skip(f"{ext_name} post_install not completed (no .post_installed stamp)")


class TestSmokeImportVerify:
    @pytest.mark.timeout(30)
    def test_import_image_deps(self):
        _skip_unless_installed("image")
        added = _add_packages_to_path()
        try:
            import numpy
            import PIL
            import cv2

            assert numpy.__version__
            assert PIL.__version__
            assert cv2.__version__
        finally:
            if added and added in sys.path:
                sys.path.remove(added)

    @pytest.mark.timeout(30)
    def test_import_animated_deps(self):
        _skip_unless_installed("animated")
        added = _add_packages_to_path()
        try:
            import PIL

            assert PIL.__version__
        finally:
            if added and added in sys.path:
                sys.path.remove(added)

    @pytest.mark.timeout(30)
    def test_import_ai_tagger_deps(self):
        _skip_unless_post_installed("ai_tagger")
        added = _add_packages_to_path()
        try:
            import onnxruntime as ort

            assert ort.__version__
        finally:
            if added and added in sys.path:
                sys.path.remove(added)

    @pytest.mark.timeout(60)
    def test_import_blip_deps(self):
        _skip_unless_post_installed("blip_captioner")
        added = _add_packages_to_path()
        try:
            import torch
            import transformers

            assert torch.__version__
            assert transformers.__version__
        finally:
            if added and added in sys.path:
                sys.path.remove(added)

    @pytest.mark.timeout(30)
    def test_ffmpeg_binaries_exist(self):
        _skip_unless_post_installed("ffmpeg")
        from extensions.ffmpeg._downloader import get_ffprobe_path, get_ffmpeg_path

        assert get_ffprobe_path() is not None, "ffprobe.exe not found"
        assert get_ffmpeg_path() is not None, "ffmpeg.exe not found"

    @pytest.mark.timeout(30)
    def test_exiftool_binary_exists(self):
        _skip_unless_post_installed("exiftool")
        from extensions.exiftool._downloader import get_exiftool_path

        assert get_exiftool_path() is not None, "exiftool not found"

    @pytest.mark.timeout(30)
    def test_video_dll_exists(self):
        _skip_unless_post_installed("video")
        from extensions.video._downloader import _DLL_PATH

        assert os.path.isfile(_DLL_PATH), f"libmpv-2.dll not found at {_DLL_PATH}"


class TestSmokeGPUVerify:
    @pytest.mark.timeout(60)
    def test_ai_tagger_gpu_provider(self, request):
        if request.config.getoption("--allow-cpu-fallback"):
            pytest.skip("--allow-cpu-fallback: skipping GPU assertion")
        _skip_unless_post_installed("ai_tagger")
        added = _add_packages_to_path()
        try:
            import onnxruntime as ort
            from extensions.ai_tagger._inference import _preload_cuda_libs

            _preload_cuda_libs()
            available = ort.get_available_providers()
            gpu_providers = ("CUDAExecutionProvider", "ROCmExecutionProvider", "CoreMLExecutionProvider")
            assert any(p in available for p in gpu_providers), f"No GPU provider found in onnxruntime. Available: {available}. Ensure CUDA and cuDNN are properly installed."

            from extensions.ai_tagger._downloader import ensure_model

            model_dir = ensure_model()
            providers = [p for p in available if p != "TensorrtExecutionProvider"]
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            session = ort.InferenceSession(str(model_dir / "model.onnx"), providers=providers, sess_options=opts)
            active = session.get_providers()
            del session
            assert any(p in active for p in gpu_providers), f"GPU provider listed ({available}) but session fell back to CPU ({active}). CUDA/cuDNN DLLs may be missing."
        finally:
            if added and added in sys.path:
                sys.path.remove(added)

    @pytest.mark.timeout(60)
    def test_blip_gpu_device(self, request):
        if request.config.getoption("--allow-cpu-fallback"):
            pytest.skip("--allow-cpu-fallback: skipping GPU assertion")
        _skip_unless_post_installed("blip_captioner")
        added = _add_packages_to_path()
        try:
            import torch

            assert torch.cuda.is_available(), "torch.cuda.is_available() returned False. Ensure CUDA-enabled PyTorch is installed."
            device_name = torch.cuda.get_device_name(0)
            assert device_name, "CUDA device name is empty"
        finally:
            if added and added in sys.path:
                sys.path.remove(added)


class TestSmokeInferenceVerify:
    @pytest.mark.timeout(120)
    def test_ai_tagger_inference(self):
        _skip_unless_post_installed("ai_tagger")
        added = _add_packages_to_path()
        try:
            from PIL import Image
            from extensions.ai_tagger._downloader import ensure_model
            from extensions.ai_tagger._inference import WD14Inference

            model_dir = ensure_model()
            engine = WD14Inference(model_dir)

            test_image = Image.new("RGB", (256, 256), color="red")
            result = engine.predict(test_image)

            assert "ratings" in result, f"Missing 'ratings' key in result: {list(result.keys())}"
            assert "general" in result, f"Missing 'general' key in result: {list(result.keys())}"
            assert "character" in result, f"Missing 'character' key in result: {list(result.keys())}"

            del engine
        finally:
            if added and added in sys.path:
                sys.path.remove(added)

    @pytest.mark.timeout(180)
    def test_blip_inference(self):
        _skip_unless_post_installed("blip_captioner")
        added = _add_packages_to_path()
        try:
            from PIL import Image
            from extensions.blip_captioner._downloader import ensure_model
            from extensions.blip_captioner._inference import BlipInference

            model_dir = ensure_model()
            engine = BlipInference(model_dir)

            test_image = Image.new("RGB", (256, 256), color="red")
            caption = engine.predict(test_image)

            assert isinstance(caption, str), f"Expected str, got {type(caption)}"
            assert len(caption) > 0, "Caption is empty"

            del engine
        finally:
            if added and added in sys.path:
                sys.path.remove(added)
