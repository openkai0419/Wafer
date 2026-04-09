<div align="center">
# Wafer

![Wafer Screenshot](_docs/wafer_screenshot.png)
</div>

Wafer is an extensible & flexible local file viewer with background metadata collection.
Core feature based on PySide, Sqlite, and Zmq.
Only supports on Windows currently. Other OS contributions are welcome.

## Installation

### in packaged

### in local python

#### Requirements

- Python 3.10+
- Windows (currently the only tested OS)

#### Setup

```bash
# 1. Run setup.bat to create venv and install all dependencies
setup.bat

# 2. Run the app in dev mode
python main.py --dev

# 3. Run tests
python -m pytest tests/
```
## Design

Wafer has a principle 
**"one foundation, many extensions"**.

- **`wafer/`** is the stable common foundation — it provides infrastructure for file collection, database indexing, search, and rendering, independent of any specific file format.
- **`extensions/`** contains independent, folder-based extensions that implement support for specific file formats (images, video, audio, etc.).

The core design goals are:

1. **The foundation is stable; extensions are free.** The foundation is carefully designed and tested. Extensions can be added, modified, or removed by anyone.
2. **Extensions are first-class participants, not restricted guests.** Extensions can directly import `wafer` internals (`wafer.plugin`, `wafer.utils`, `wafer.core`). They are part of the same ecosystem, not walled off behind an API boundary.
3. **Extensions are independent of each other.** The image extension does not know about the video extension. Each extension communicates with the foundation through `wafer/` alone.

The ideal form of this project is an ecosystem where multiple developers freely build file format support on top of a shared `wafer/` foundation.

Extensions are placed as folders under `extensions/`. `PluginLoader` (`wafer/plugin/loader.py`) auto-discovers and registers them at startup.

## Currently Supporting Extensions


### How It Works

1. If `requirements.txt` exists and dependencies are not installed (or outdated), they are auto-installed to `.packages/` via pip
2. `.packages/` is added to `sys.path`
3. `lib/` is added to DLL search paths
4. All `*.py` files are imported and plugin classes are auto-discovered by inheritance
5. In frozen (exe) builds, pip is invoked via `pip._internal.cli.main` (bundled as hidden import)

### Extension Examples

Extensions import base classes from `wafer.plugin`:

## Data Files

Application data is stored via `platformdirs` (`AppData/Local` on Windows).
`_resources/` contains UI assets and binding presets that users can customize.

## License

The core foundation (`wafer/`) and most extensions are licensed under the [Apache License 2.0](LICENSE).

Extensions with different licenses have their own `LICENSE` file in their directory. If an extension does not include a `LICENSE` file, the root Apache-2.0 license applies.

| Component | License |
|---|---|
| `wafer/` (core) | Apache-2.0 |
| `extensions/video/` | AGPL-3.0 (due to python-mpv dependency) |
| All other extensions | Apache-2.0 |