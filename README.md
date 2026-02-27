# AfterImages

Image viewer and metadata finder.

## Overview

This project provides an image viewer with background metadata collection. The viewer is built with **PySide6** and allows browsing images with metadata search. The collector watches specified folders and indexes files into a local SQLite database.

Future goals include video/audio/Zip support and a user-extensible plugin system.

## Requirements

- Python 3.10+
- Windows (currently the only tested OS)

## Setup

```bash
# 1. Run setup.bat to create venv and install all dependencies
setup.bat

# 2. Run the app in dev mode
python main.py --dev

# 3. Run tests
python -m pytest tests/
```

## Build

```bash
# Build a distributable exe with PyInstaller
build.bat
# Output: dist/AfterImages/main.exe
```

`build.bat` does the following:
- Runs PyInstaller with `main.spec`
- Copies `_resources/` and `plugins/` into the dist folder
- `plugins/.vendor/` and `__pycache__/` are excluded from dist (plugin dependencies are auto-installed at first run via bundled pip)

## Project Structure

```
main.py              Entry point
source/              Application source code
plugins/             External plugins (folder-based, auto-detected by PluginLoader)
tests/               Tests (tests/source/, tests/plugins/, tests/prototypes/)
_resources/          UI resources, key/mouse binding presets
prototypes/          Experimental/prototype code
.temp/               Temporary debug files and caches
```

### Configuration Files

| File | Purpose |
|---|---|
| `requirements.txt` | Runtime dependencies (14 packages) |
| `requirements-dev.txt` | Dev dependencies (`-r requirements.txt` + pyinstaller, pytest) |
| `pyproject.toml` | pytest configuration only (pythonpath, importlib mode). No package metadata |
| `main.spec` | PyInstaller build spec (includes bundled pip for frozen plugin installs) |
| `setup.bat` | Creates `.venv` and installs `requirements-dev.txt` |
| `build.bat` | Builds distributable exe via PyInstaller |

## Plugins

Plugins are placed as folders under `plugins/`. `PluginLoader` (`source/io/loader.py`) auto-discovers and registers them at startup.

### Plugin Folder Structure

```
plugins/<name>/
  *.py                Plugin classes (subclass BaseViewerPlugin / BaseGridPlugin / BaseCollectorPlugin)
  requirements.txt    Python dependencies (optional)
  lib/                Native DLLs (optional, auto-added to PATH)
  .vendor/            pip install target (auto-generated, git-ignored)
```

### How It Works

1. If `requirements.txt` exists and dependencies are not installed (or outdated), they are auto-installed to `.vendor/` via pip
2. `.vendor/` is added to `sys.path`
3. `lib/` is added to DLL search paths
4. All `*.py` files are imported and plugin classes are auto-discovered by inheritance
5. In frozen (exe) builds, pip is invoked via `pip._internal.cli.main` (bundled as hidden import)

### Example: Image Plugin

The built-in image plugin is at `plugins/image/` with its own `requirements.txt` (numpy, opencv-python, pillow). It provides Grid, Viewer, and Collector plugins for image files.

### Plugin API

Plugin classes import base classes from the `afterimages` module:

```python
from afterimages import BaseViewerPlugin, BaseGridPlugin, BaseCollectorPlugin, CollectorResult
```

Each plugin class must have a `NAME` class variable and inherit from one of the base classes.

## Data Files

Application data is stored via `platformdirs` (`AppData/Local` on Windows).
`_resources/` contains UI assets and binding presets that users can customize.

## OS Support

Currently Windows only. Other OS contributions are welcome.