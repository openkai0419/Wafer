# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [v0.6.0]
### Added
- **Portable build system**: replaced PyInstaller with Python-bundling approach — `scripts/build.py` now downloads embeddable Python 3.11, installs pip and runtime deps, copies source, and compiles C# launcher executables
- `scripts/launcher/Wafer.cs` and `WaferConsole.cs`: C# launchers for windowed and console mode
- `main.bat` now pauses on non-zero exit code
- Extension `requirements.txt` files now explicitly pin shared dependencies (`pillow`, `numpy`) per-extension

### Changed
- **Plugin installer rewritten**: removed embedded Python download/setup; now uses host `sys.executable` directly. Per-extension `.packages/` dirs replaced with single shared `extensions/.packages/` with `_merge_requirements()` for version conflict resolution (highest pinned version wins). Install stamps moved to `.stamps/` subdirectory
- `get_app_root_dir()`, `AppProcess.base_command()`, `get_version()`, and `get_plugin_dir()` no longer use `sys.frozen` check — simplified for portable (non-PyInstaller) build
- `main.py` stdout/stderr `StringIO` fallback now applies unconditionally (not only when frozen)
- Plugin loader: shared packages loaded from `extensions/.packages/` instead of per-extension vendor dirs; per-extension `.packages/` no longer added to `sys.path`
- `cleanup.bat` updated with improved logging and adapted for new `.packages` directory structure
- `BlipCaptionerCollector.post_install` now passes explicit timeout for torch downloads

### Removed
- `main.spec` (PyInstaller spec file)
- `extensions/requirements.txt` (shared deps moved into individual extension requirements)
- `pyinstaller` and `pyinstaller-hooks-contrib` from `requirements-dev.txt`
- `sys.frozen` checks removed from `wafer/_version.py`, `wafer/utils/paths.py`, `wafer/core/platform/process.py`, `wafer/plugin/loader.py`

## [v0.5.9]
### Added
- **BLIP Captioner extension** (`extensions/blip_captioner/`): singleton collector for generating image captions using Salesforce BLIP model, with GPU/CPU fallback, idle engine unloading, hash/pixel caching, and auto-download via HuggingFace Hub
- `faulthandler` crash logging: opt-in via `WAFER_FAULTHANDLER=1` env var, writes crash logs to `.crashlog/` directory
- Crash log cleanup (`_cleanup_crash_logs`) in `AppLogger` initialization — removes empty and rotates old crash logs
- `atexit` handler and `BaseException` catch in `main.py` for process exit logging and fatal crash reporting
- Version stamp mechanism in `EmbeddedPython` to detect Python version mismatches and auto-purge outdated embedded runtimes
- Thread-safe directory-level locking (`_get_dir_lock`) in plugin installer for concurrent install safety
- `PluginManagerWidget` connects to `ViewerIpcBridge.db_content_updated` to mark collectors tab dirty and refresh on next show
- `PluginManagerWidget` now preserves scroll position when refreshing Collectors and Order tabs

### Changed
- Renamed "Detacher" to "Parser" across all internal code, modules, IPC topics, and CLI args (`wafer/plugin/detacher/` → `wafer/plugin/parser/`, `wafer/app/detacher/` → `wafer/app/parser/`, `--detacher` → `--parser`, `detach.result` → `parse.result`, `BaseDetacherPlugin` → `BaseParserPlugin`, etc.)
- Embedded Python version upgraded from 3.10.9 to 3.11.9
- Minimum Python version raised to 3.11 (`pyproject.toml`, `setup.bat`, pyright, ruff target)
- `datetime.timezone.utc` replaced with `datetime.UTC` across codebase (Python 3.11+ constant)
- `EmbeddedPython.ensure_ready()` now runs under a global lock for thread safety
- `AppLogger` log retention changed from 0 to 5 latest logs; cleanup errors now use `AppLogger.warning()` instead of `print()`
- `install_requirements` purges vendor dir when Python version changes
- IPC `Broker` poll loop now logs `ZMQError` as warning instead of silently ignoring
- Runtime and dev dependency versions bumped (blake3, comtypes, msgpack, pillow, platformdirs, psutil, pyzmq, requests, setproctitle, pyright, pytest, ruff, etc.)

### Removed
- `wafer/plugin/detacher/` package (replaced by `wafer/plugin/parser/`)
- `wafer/app/detacher/` package (replaced by `wafer/app/parser/`)
- `wafer/app/indexer/detacher_dispatcher.py` and `detacher_receiver.py` (replaced by `parser_dispatcher.py` and `parser_receiver.py`)

## [v0.5.8]
### Added
- `WindowRestartCommands` menu group: restart commands (`win.restart_all`, `win.restart_tray`, `win.restart_viewer`) registered under Window menu

### Changed
- Tray menu reorganized into logical groups: Viewer, Database, Window, Tray (separate `TrayViewerCommands`, `TrayDatabaseCommands`, `TraySystemCommands` classes)
- Restart commands moved from Settings (`app.py`) to Window menu group (`window_commands.py`)
- Help (README, About) separated into its own `Help` menu group (was part of `Setting`)
- Tray command paths prefixed with `tray.` namespace (e.g., `show_window` → `tray.show_window`)

### Fixed
- Plugin Manager collectors tab now refreshes on open and correctly preserves default/per-DB state across rebuilds
- README release links updated to correct repository URL

## [v0.5.7]
### Added
- `PluginSettings.default_enabled_collectors` / `resolve_default_collectors`: new DB creation now seeds enabled collectors from global defaults
- Multi-select ignore in FolderTree (`ignore_folder` accepts multiple paths, batch confirmation dialog)
- Copy/paste support (Ctrl+C/V) for source and ignore path lists in Database Manager
- Multi-select deletion for source/ignore path lists (`ExtendedSelection` mode)
- `CalloutOverlay.suspend` / `resume`: callout hides when window loses focus or is minimized
- `_ClickableLabel` widget in Plugin Manager collectors tab for clickable DB links

### Changed
- Renamed "Purge" to "Delete" across IPC topics (`purge.collector` → `delete.collector`, `purge.keys` → `delete.keys`), DB methods, UI labels, and signal names
- Collector worker now uses a queue-based `_batch_loop` with chunked processing (`_CHUNK_SIZE=50`) instead of spawning a thread per dispatch
- Callout overlay now checks if folders already exist before showing on first run
- Database creation (`_create_database`) moved to background thread via `Dispatcher.post`
- Extension licenses added/updated (exiftool, ffmpeg, video)
- README and README.jp.md rewritten

### Fixed
- Plugin installer not working in exe-packaged builds (path resolution fix)
- Video viewer loop default state

## [v0.5.6] - 2026-04-12
### Changed
- README formatting and content updates

## [v0.5.5] - 2026-04-12
### Changed
- GitHub Actions `build.yml` workflow configuration updates

## [v0.5.4] - 2026-04-12
### Fixed
- `option_dialog.py`: fixed `decimal.InvalidOperation` import (was using undefined `decimal` module reference)
- `meta_panel.py` / `meta_viewer.py`: removed unnecessary f-string in static CSS (no interpolation needed)
- `callout_overlay.py`: removed unused variable `w`, consolidated window flags to single line
- `cleanup.bat` rewritten with improved logic
- `scripts/test.py`: test runner improvements
- `scripts/copy_clean_project.py`: enhanced clean-copy logic

## [v0.5.3] - 2026-04-12
### Added
- **ExifTool extension** (`extensions/exiftool/`): new collector, parser, settings panel, meta panel, and auto-downloader for ExifTool binary
- **FFmpeg extension** (`extensions/ffmpeg/`): new collector, parser, and auto-downloader for FFmpeg binary
- **ComfyUI parser** (`extensions/text_generation/comfyui_parser.py`): workflow metadata extraction for ComfyUI-generated images
- **MetaPanel plugin system** (`wafer/plugin/meta_panel/`): new plugin type for extensible metadata display panels
- **Profile system** (`wafer/core/profile.py`): replaced Session with Profile — `ProfileEntry`, `ProfileStore`, `QueryState`, `UIState` as dataclasses with JSON persistence
- **ViewerIpcBridge** (`wafer/app/viewer/ipc_bridge.py`): centralized Qt signal bridge for all IPC messages (db updates, progress, folder changes, etc.)
- **CalloutOverlay** (`wafer/app/viewer/widgets/callout_overlay.py`): animated tooltip overlay with arrow, tracking, and auto-dismiss
- **Database Manager Data Tab** (`wafer/builtins/database_manager/data_tab.py`): per-prefix data inspection with row counts, delete/re-collect controls
- **Markdown browser** (`wafer/utils/markdown_browser.py`): WebEngine-based Markdown viewer with GitHub dark/light CSS themes
- **Key selector popup** (`wafer/plugin/query/widgets.py`): tree-based metadata key browser with active key filtering and catalog display
- `wafer/ui/` layer: new top-level UI package (dialogs, splash, window, layout, settings, file conflict resolver — all moved from `core/`)
- README files added for all extensions (image, animated, video, ai_tagger, additional_filters, additional_layout, text_generation)
- LICENSE and NOTICE added to repository root
- `cleanup.bat`, `scripts/lint.py`, `scripts/test.py` build/dev tooling
- GitHub Actions `build.yml` CI workflow

### Changed
- **Session → Profile rename**: `session.py` → `profile.py`, `SessionEntry` → `ProfileEntry`, `SessionStore` → `ProfileStore`, `session_commands.py` → `profile_commands.py`, `session_popup.py` → `profile_popup.py`
- **Package restructure**: `wafer/core/layout/` → `wafer/ui/layout/`, `wafer/core/setting/` → `wafer/ui/settings/`, `wafer/core/qt/dialog.py` → `wafer/ui/dialogs.py`, `wafer/core/qt/window.py` → `wafer/ui/window.py`, `wafer/core/qt/splash.py` → `wafer/ui/splash.py`
- **Image EXIF extraction delegated to ExifTool**: removed `extensions/image/collector.py` and `extensions/image/exif_parser.py`, image metadata now collected via exiftool extension
- **IPC refactored**: MainWindow no longer subscribes to IPC directly; all message routing goes through `ViewerIpcBridge` with Qt signals
- Video playback slot manager now has idle cooldown (`_cooldown` / `_cooled_down`) to release resources when idle
- `TranslatorMixin` removed from MainWindow; direct `t()` function calls used instead
- `plugin/query/widgets.py` expanded with `_ActiveKeyItem`, `_KeySelectorPopup` for interactive metadata key filtering
- Filter widget, regex filter, and layout plugins refactored for clarity
- Indexer scanner, watch_folder, and dispatchers refactored
- AppLogger refactored with improved formatting and remote log relay
- Plugin installer rewritten with clearer flow and SHA256 verification for get-pip.py

### Removed
- `wafer/core/session.py` (replaced by `wafer/core/profile.py`)
- `wafer/builtins/plugin_manager/data_tab.py` (moved to `wafer/builtins/database_manager/data_tab.py`)
- `extensions/image/collector.py` and `extensions/image/exif_parser.py` (functionality moved to exiftool extension)
- `wafer/core/setting/` package (moved to `wafer/ui/settings/`)
- `.github/` config files (copilot-instructions, memory, plan, rule, code_review, AGENTS.md)

## [v0.5.2] - 2026-04-06
### Added
- Version management (`wafer/_version.py`)

## [v0.5.1] - 2026-04-06
- Initial public release
- Core viewer: grid view, image/video preview, file viewer
- Plugin architecture: collector, parser, grid, layout, query, rename, viewer, panel plugin types with auto-discovery via `PluginLoader`
- Database system: SQLite-based file metadata DB with setting DB, indexer process, scanner, watch folder
- IPC system: ZMQ-based multi-process communication (Node, Outbox, Transport)
- Command system: key/mouse binding, command registry, options dialog
- UI: MainWindow, FolderTree, search container, progress bar, profile popup, loading overlay
- Extensions: image, animated (GIF/APNG), video (mpv-based), ai_tagger (WD14), additional_filters (regex), additional_layout (justified/organic/multispan), text_generation (prompt parser)
- Batch renamer with preview and conflict resolution
- App settings, theme system, translation (i18n) support
