# AfterImages

Extensible local file viewer with background metadata collection.

## Design Philosophy

AfterImages is built around the principle **"one foundation, many extensions"**.

- **`afterimages/`** is the stable common foundation — it provides infrastructure for file collection, database indexing, search, and rendering, independent of any specific file format.
- **`extensions/`** contains independent, folder-based extensions that implement support for specific file formats (images, video, audio, etc.).

The core design goals are:

1. **The foundation is stable; extensions are free.** The foundation is carefully designed and tested. Extensions can be added, modified, or removed by anyone.
2. **Extensions are first-class participants, not restricted guests.** Extensions can directly import `afterimages` internals (`afterimages.plugin`, `afterimages.utils`, `afterimages.core`). They are part of the same ecosystem, not walled off behind an API boundary.
3. **Extensions are independent of each other.** The image extension does not know about the video extension. Each extension communicates with the foundation through `afterimages/` alone.

The ideal form of this project is an ecosystem where multiple developers freely build file format support on top of a shared `afterimages/` foundation.

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
- Copies `_resources/` and `extensions/` into the dist folder
- `extensions/.packages/` and `__pycache__/` are excluded from dist (extension dependencies are auto-installed at first run via bundled pip)

## Project Structure

```
main.py              Entry point
afterimages/         Common foundation (utils, core, plugin, app)
extensions/          File format extensions (folder-based, auto-detected by PluginLoader)
tests/               Tests (tests/afterimages/, tests/extensions/, tests/prototypes/)
_resources/          UI resources, key/mouse binding presets
prototypes/          Experimental/prototype code
.temp/               Temporary debug files and caches
```

### Configuration Files

| File | Purpose |
|---|---|
| `requirements.txt` | Runtime dependencies |
| `requirements-dev.txt` | Dev dependencies (`-r requirements.txt` + pyinstaller, pytest, etc.) |
| `pyproject.toml` | pytest configuration only (pythonpath, importlib mode). No package metadata |
| `main.spec` | PyInstaller build spec (includes bundled pip for frozen extension installs) |
| `setup.bat` | Creates `.venv` and installs `requirements-dev.txt` |
| `build.bat` | Builds distributable exe via PyInstaller |

## Extensions

Extensions are placed as folders under `extensions/`. `PluginLoader` (`afterimages/plugin/loader.py`) auto-discovers and registers them at startup.

### Extension Folder Structure

```
extensions/<name>/
  *.py                Plugin classes (subclass BaseViewerPlugin / BaseGridPlugin / BaseCollectorPlugin)
  requirements.txt    Python dependencies (optional)
  lib/                Native DLLs (optional, auto-added to PATH)
  .packages/          pip install target (auto-generated, git-ignored)
```

### How It Works

1. If `requirements.txt` exists and dependencies are not installed (or outdated), they are auto-installed to `.packages/` via pip
2. `.packages/` is added to `sys.path`
3. `lib/` is added to DLL search paths
4. All `*.py` files are imported and plugin classes are auto-discovered by inheritance
5. In frozen (exe) builds, pip is invoked via `pip._internal.cli.main` (bundled as hidden import)

### Example: Image Extension

The built-in image extension is at `extensions/image/` with its own `requirements.txt` (numpy, opencv-python, pillow). It provides Grid, Viewer, and Collector plugins for image files.

### Extension API

Extensions import base classes from `afterimages.plugin`:

```python
from afterimages.plugin import BaseViewerPlugin, BaseGridPlugin, BaseCollectorPlugin, CollectorResult
```

Extensions can also directly import from `afterimages.utils` and `afterimages.core` as needed:

```python
from afterimages.utils.logs import AppLogger
from afterimages.core.db.query import FileSearchEngine
```

Each plugin class must have a `NAME` class variable and inherit from one of the base classes.

## Data Files

Application data is stored via `platformdirs` (`AppData/Local` on Windows).
`_resources/` contains UI assets and binding presets that users can customize.

## OS Support

Currently Windows only. Other OS contributions are welcome.