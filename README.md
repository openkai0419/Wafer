<div align="center">

# Wafer

![Wafer Screenshot](_docs/wafer_screenshot.png)

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)
![Release](https://img.shields.io/github/v/release/openkai0419/Wafer?style=flat-square)
![Release Date](https://img.shields.io/github/release-date/openkai0419/Wafer?style=flat-square)
![Downloads](https://img.shields.io/github/downloads/openkai0419/Wafer/total?style=flat-square)

[日本語はこちら](README.jp.md)

</div>

Wafer is an extensible local file viewer built on **PySide6**, **SQLite**, and **ZMQ**.
Collections runs in background process, letting you browse and search across huge amout of files.
Plugin-based extensions add support for any file format. Currently Windows only — other OS contributions are welcome.

## Installation

### From zip 

1. Go to [Releases](https://github.com/openkai0419/private_rep/releases/latest)
2. Download `Wafer-vX.X.X.zip`
3. Extract the zip to any folder (prefer SSD)
4. Run `Wafer.exe`

To uninstall, run `cleanup.bat` to remove app data from `%LOCALAPPDATA%\Wafer`, and delete the extracted files.

### From Source

#### Requirements

- Python 3.10+
- Windows (currently the only tested OS)

#### Setup

```bash
git clone https://github.com/openkai0419/Wafer.git
cd Wafer

# Create venv and install all dependencies
setup.bat

# Run the app
python main.py

# Run tests (layered runner: unit → smoke → benchmark)
scripts\test.bat

# Or run pytest directly (uses pyproject.toml defaults)
.venv\Scripts\python.exe -m pytest
```

## Design

Wafer follows the principle **"one foundation, many extensions"**.

- **`wafer/`** is the common foundation — it provides infrastructure for file collection, database indexing, search, and rendering, independent of any specific file format.
- **`extensions/`** contains independent, folder-based extensions that implement support for specific file formats (images, video, audio, etc.).

The core design goals are:

1. **The foundation is shared; extensions are free.** The foundation aims to be a reliable common base. Extensions can be added, modified, or removed by anyone without touching it.
2. **Extensions are first-class participants, not restricted guests.** Extensions can directly import `wafer` internals (`wafer.plugin`, `wafer.utils`, `wafer.core`). They are part of the same ecosystem, not walled off behind an API boundary.
3. **Extensions are independent of each other.** The image extension does not know about the video extension. Each extension communicates with the foundation through `wafer/` alone.

The ideal form of this project is an ecosystem where multiple developers freely build file format support on top of a shared `wafer/` foundation.

Extensions are placed as folders under `extensions/`. `PluginLoader` auto-discovers and registers them at startup.

## Currently Supporting Extensions

#### Viewer / Grid

| Extension | Formats | Description |
|---|---|---|
| **image** | jpg, png, bmp, gif, webp | Static image grid and viewer with zoom/pan |
| **animated** | gif, apng, webp (animated) | Frame-by-frame animated playback in grid and viewer |
| **video** | mp4, mkv, webm, avi, mov, etc. | Video playback via mpv with OpenGL rendering |

#### Metadata / Collection

| Extension | Formats | Description |
|---|---|---|
| **exiftool** | jpg, png, webp, tiff, heic, avif, jxl, raw, psd, etc. | Universal EXIF/IPTC/XMP metadata extraction via ExifTool |
| **ffmpeg** | mp4, mkv, webm, mp3, flac, wav, etc. | Video/audio metadata extraction via ffprobe |
| **ai_tagger** | *(images)* | WD14 model-based automatic tagging (ONNX, GPU accelerated) |
| **text_generation** | *(images with EXIF)* | NovelAI generation parameter extraction |

#### UI

| Extension | Description |
|---|---|
| **additional_filters** | Date-range and regex query filters |
| **additional_layout** | Multi-span, justified, and organic partition grid layouts |

### How It Works

1. If `requirements.txt` exists and dependencies are not installed (or outdated), they are auto-installed to `.packages/` via pip
2. `.packages/` is added to `sys.path`
3. `lib/` is added to DLL search paths
4. All `*.py` files are imported and plugin classes are auto-discovered by inheritance
5. In frozen (exe) builds, pip is invoked via an embedded Python environment

### Extension Examples

Extensions import base classes from `wafer.plugin`. Note that the foundation is not yet stable, so external plugins may break on updates.

```python
from wafer.plugin import BaseCollectorPlugin, CollectorResult

class MyCollector(BaseCollectorPlugin):
    NAME = "my_ext"
    EXTENSIONS = (".custom",)

    def collect(self, path: str) -> CollectorResult:
        return CollectorResult(meta_info={"key": "value"})
```

## Data Files

Application data is stored via `platformdirs` (`AppData/Local` on Windows).
`_resources/` contains UI assets and binding presets that users can customize.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

**Our intent:**
Wafer's foundation (`wafer/`) is designed to be a shared core that benefits every extension and every user. While the Apache-2.0 license grants full freedom to use, modify, and redistribute, we kindly ask that improvements to the core be contributed back upstream so the entire ecosystem can grow together.

Extensions (`extensions/`) are yours to create, modify, and license however you wish. Each extension may include its own `LICENSE` file to specify different terms. If an extension does not include one, the root Apache-2.0 license applies.

| Component | License | Reason |
|---|---|---|
| `wafer/` (core) | Apache-2.0 | — |
| `extensions/video/` | GPL-2.0+ | libmpv / python-mpv (GPL-2.0+ default build) |
| `extensions/exiftool/` | GPL-3.0 | ExifTool binary (GPL-3.0) |
| `extensions/ffmpeg/` | GPL-3.0+ | FFmpeg/FFprobe binary (`--enable-gpl --enable-version3`) |
| All other extensions | Apache-2.0 | Unless specified by their own `LICENSE` |