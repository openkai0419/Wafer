# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [0.6.9]
### Added
- **ZIP archive extension** (`extensions/zip/`): `ZipCollectorPlugin` indexes entries inside `.zip` files as virtual paths with aspect-ratio probing; `ZipGridPlugin` and `ZipViewerPlugin` materialize entries via `ZipCache` (LRU + idle-sweep eviction) for grid and file viewer
- **Virtual path system** (`wafer/utils/virtual_paths.py`): `build_virtual_path()` / `split_virtual_path()` / `is_virtual_path()` and related helpers encode archive member paths as `source::member`; `register_owner_extension()` / `IS_OWNER` plugin flag declare which collectors own virtual children
- **`RenderTarget` / `ResolveContext`** (`wafer/core/files/render_target.py`): immutable render-dispatch value type with depth-limited recursive resolution; adopted by `GridResolver.resolve_target()` and `ViewerResolver.resolve_target()`, routing virtual paths to owner-plugin `resolve_target()` before the normal chain
- **`DISPATCH_OWNER` / `DISPATCH_LEAF` registry modes**: `FilePluginRegistry.resolve()` / `resolve_chain()` accept a mode for owner- or leaf-extension-based dispatch
- **Standard key constants** (`wafer/core/db/query.py`): `SYSTEM_FILE_HASH_KEY`, `STANDARD_KEYS`, `standard_key_columns()` — standard fields resolve directly from dedicated DB columns, eliminating `meta_info` round-trips for path/name/size/modified/created/collected/file_hash queries

### Changed
- **DB schema**: `sources` gains `created` and `collected` columns; `files` gains `name` and `source_extension` columns; `files_full` view and indexes updated; `path`/`name`/`size`/`modified`/`created`/`collected` entries are no longer written to `meta_info` during basic indexing
- **Schema migration** (`FileDB._recreate_tables()`): changed tables are backed up, recreated, and data-migrated column-by-column instead of being dropped
- **`TextFilter` / `SearchQuery` / `SearchComposer`**: standard keys and `file_hash` route to DB columns; `available_keys()` includes standard keys; sort plugins use `SORT_COLUMN` instead of `META_KEY`, eliminating `meta_info` JOIN for common sort fields
- **`GridPipeline` / `FileViewerController`**: refactored to use `RenderTarget` throughout; virtual-path entries are resolved and rendered via the correct materialized path
- **`CollectorResult`** gains `size`, `modified`, `created` fields; `FileDB.upsert_collection_results()` cleans up stale virtual child rows after successful collection; `delete_collector()` also removes child rows keyed by `source_extension`
- File rename propagation extended to virtual child paths; batch renamer and file commands updated to use physical source paths correctly
- Plugin kind badge colors updated (`wafer/plugin/kinds.py`)

## [v0.6.8]
### Added
- **`wafer/plugin/kinds.py`**: centralized plugin-kind labels, colors, and ordering shared by the loader and Plugin Manager UI
- **`wafer/ui/popups.py`** (`PopupBase`): reusable anchored popup frame with screen clamping and Escape-to-close behavior, adopted by workspace, text-filter, and batch-renamer popups
- **Editable `meta_info` support**: `MetaViewerWidget`, `EditableTagCard`, `TagEditService`, `DatabaseWriter.apply_user_kv()`, and `FileDB.apply_user_meta_info()` now allow adding, renaming, deleting, and locking user metadata keys alongside tags

### Changed
- **Plugin Manager UI**: extension cards, badge tooltips, and order views now use centralized plugin-kind metadata so collector/parser/panel/loader/command badges render with consistent labels and colors
- **Metadata panel** (`wafer/app/viewer/preview/meta_panel.py`): root metadata is split from standard file fields, tag/meta sections get visual markers, and the add dialog can target either tags or metadata depending on current file context
- **Meta panel plugin API**: `BaseMetaPanelPlugin.update_data()` now receives `locks`, `path`, and `db`, and the built-in ffmpeg/exiftool panels were updated to the new signature

### Fixed
- **Locked metadata preservation**: `meta_info` now migrates a `locked` column when missing, collector upserts skip locked rows, and delete/cleanup paths avoid removing locked user metadata
- Scope-aware `tags.updated` acknowledgements now return target IDs for both tags and metadata, keeping overlay state and metadata reloads synchronized after edits

## [v0.6.7]
### Added
- **Workspace persistence system** (`wafer/core/workspace.py`): JSON-backed `WorkspaceStore`, `WindowSlot`, and UI/path/query preset dataclasses with active/restore slot tracking
- **Workspace toolbar** (`wafer/app/viewer/widgets/workspace_toolbar.py`): compact Recent/UI/Path/Filter popups for saving, applying, overwriting, renaming, and deleting presets and recent workspace slots
- **Workspace commands** (`wafer/builtins/commands/workspace.py`): `ws.*`, `ui_preset.*`, `path_preset.*`, and `query_preset.*` commands replacing profile/bookmark commands with slot and preset operations
- **State coordinators** (`wafer/app/viewer/state_coordinator.py`): separate UI, path, and query capture/restore flows used by window slots and presets
- **Inline menu actions** (`MenuAction` / `ActionKit.Action`): command-menu builder can now host lightweight non-registered actions for context menus and inline popups
- **FolderTree recursive expand/collapse** (`wafer/app/viewer/widgets/foldertree.py`): Shift-clicking a branch indicator expands or collapses a subtree using batched background scanning with cancellation
- **`ElidingLabel` / `ElidingToolButton`** (`wafer/ui/widgets/eliding.py`): reusable eliding text widgets used by workspace and plugin-manager UI
- App-settings synchronization across viewers via `settings.changed` IPC and `SettingManager.committed` / `key_changed` signals
- New themed icons: `history`, `save`, `pencil`, and `trash`

### Changed
- **Profile system replaced by workspace slots**: viewer CLI now uses `--slot` instead of `--profile`; IPC topics changed from `profile.close` / `profile.restart` to `slot.close` / `slot.restart`; tray/viewer restore logic now uses `WorkspaceStore`
- **`MainWindow` state persistence**: window geometry/UI state, selected database/folders, and query bars are saved into `WindowSlot` snapshots instead of `ProfileStore` and `app_settings`
- **Search filter bars** (`wafer/app/viewer/widgets/search_container.py`): rows now support context-menu enable/disable, insert-after, move up/down/top/bottom, and delete actions; saved state uses `bars` and can be applied in replace or append mode
- Query sort/order command check states now resolve from live `SearchService` values instead of persisted action-group state
- Grid orientation, layout mode, and scroll anchor check states now resolve from live `GridView` state; `GridView` stores `scroll_anchor` directly and applies scrollbar policies based on orientation
- **Plugin UI state API**: plugin bases and built-in/extension implementations renamed `save_state()` / `restore_state()` to `save_ui_state()` / `restore_ui_state()`; `BasePanelPlugin.plugin_config` can declare the panel-owned `PluginConfig`
- **ExifTool settings** (`extensions/exiftool/settings.py`): filter and sort settings now use `PluginConfig`, with filter changes saved through `save_and_notify()`
- Active metadata key selection and mark overlay visibility/radius moved from global `app_settings` to window-scoped `StateStore`
- `SearchContainer`, mark, rename dropdown, folder-list, binding-override, and sort popups now use the shared command-menu framework instead of direct ad-hoc `QMenu` actions

### Fixed
- Tag update acknowledgements now force a current-DB search refresh, keeping tag edits, mark filters, and grid overlays in sync after writes
- `FileListProvider.set_mode()` now immediately syncs from current grid results when switching back to sync mode
- `MarkRegistry` refreshes mark definitions when remote settings changes arrive, keeping multi-window mark color/name state synchronized
- `Dispatcher.invoke()` now checks parent QObject validity before emitting, avoiding queued callbacks to deleted parents
- Broker active/restore slot updates now use a locked debounce timer that is cancelled safely during shutdown

### Removed
- `wafer/core/profile.py` and `wafer/builtins/commands/profile.py` profile/bookmark storage and commands, replaced by workspace slots plus UI/path/query presets

## [v0.6.6]
### Added
- **`value_viewer_dialog.py`** (`wafer/ui/panel/value_viewer_dialog.py`): shared full-value dialog with selectable key label and read-only text area
- `SearchableMetaWidget` double-click and context menu support for opening full metadata values and copying key, value, or row text

### Changed
- **`FileSearchEngine.get_tag_keys_for_paths()` renamed to `get_tag_keys_by_prefix()`**: supports full-DB prefix fetch with `paths=None` and path-restricted fetch with `paths=[...]`
- **`MarkOverlayService`** now reloads a whole-DB mark cache on database/search reload and rejects stale async reload results by sequence number instead of tracking only the current result paths
- `MetaRowWidget` now uses the shared value viewer dialog for full metadata display

## [v0.6.5]
### Added
- **Mark system** (`wafer/builtins/mark/`): user-defined named, colored marks stored in `app_settings`; `MarkRegistry` singleton with `Mark` dataclass, color swatch icon generation, and duplicate-name resolution on load
- **Mark commands** (`wafer/builtins/mark/commands.py`): `mark.add`, `mark.remove`, `mark.toggle`, `mark.clear`, `mark.define`, `mark.rename`, `mark.set_color`, `mark.remove_def` registered under `File/Mark` menu group via `MarkCommands`
- **`MarkOverlayService`** (`wafer/app/viewer/grid/mark_overlay_service.py`): background-loaded mark data per grid item; draws colored dot badges (single color, pie segments, or rainbow for 5+ marks) on grid overlay; configurable radius and visibility saved to `app_settings`
- **`MarkTagPanelPlugin`** (`wafer/builtins/mark/panel.py`): `BaseTagPanelPlugin` implementation displaying mark-badge row in the metadata side panel with per-mark toggle and "Add new mark" button
- **`MarkFilter`** (`wafer/builtins/filters.py`): new `BaseFilterPlugin` for filtering by selected marks; `MarkFilterWidget` shows per-mark toggle buttons with match count and OR/AND mode popup; mark overlay settings (visibility, radius) accessible from filter widget
- **`EditableTagCard`** (`wafer/app/viewer/preview/editable_tag_card.py`): inline tag editor in the metadata panel — add, delete, rename, and lock/unlock individual tags; `LineEditor` and `PlainEditor` inline widgets with commit-on-Enter/blur and Escape-to-cancel; `AddTagDialog` for adding new tags
- **`TagEditService`** (`wafer/app/viewer/preview/tag_edit_service.py`): singleton handling in-flight tag edit tracking, IPC submission via `tags.update`, timeout/fail detection, and `commit_confirmed` signal for panel reload on write confirmation
- **`BaseTagPanelPlugin`** (`wafer/plugin/tag_panel/`): new plugin type for tag section cards rendered in the metadata panel; auto-discovered via `tag_panel_registry`
- **`ColorPickerDialog`** (`wafer/ui/widgets/color_picker.py`): custom HSV color picker with hue ring + saturation/value square (`HueRingSVSquare`), hex/RGB input fields, optional alpha channel, and persistent recent color swatches; used for mark color assignment
- **`FlowLayout`** (`wafer/ui/widgets/flow_layout.py`): reusable wrapping flow layout widget for badge/button rows
- **`wafer/utils/recent_colors.py`**: persistent recent colors list (load/save) used by `ColorPickerDialog`
- **`tags.update` / `tags.updated` IPC topics**: indexer handles user tag writes via `_on_tags_update()`; runs `apply_user_tags()` as a `USER_REQUEST` priority task; replies to viewer with per-path applied/deleted/file_hash results
- **`FileDB.apply_user_tags()`**: writes user-managed tags (upsert/delete/rename) with lock support across multiple paths, returning per-path results
- **`FileDB._migrate_tags_on_hash_change()`**: preserves existing tags (including locked user tags) when a file's content hash changes during indexing
- **`FileSearchEngine.get_tag_keys_for_paths()`**: batch fetches tag key suffixes by prefix for a list of paths; used by `MarkOverlayService` to load mark data
- **`FileSearchEngine.close()`**: explicit connection close for use outside long-lived query flows
- **`DatabaseWriter.apply_user_tags()`**: wraps `FileDB.apply_user_tags()` with WAL checkpoint
- New themed icons: `empty`, `checkbox_unchecked`, `checkbox_checked`, `lock`, `lock_open`

### Changed
- **`tags` table schema**: `locked INTEGER NOT NULL DEFAULT 0` column added; collector upserts (`_SQL_UPSERT_TAGS`) have `WHERE tags.locked = 0` guard preserving user-locked tags; `delete_collector`, `delete_keys`, and per-file delete operations also filter `locked = 0`
- **`FileSearchEngine.get_tags_by_path()`** renamed to `get_tags_with_lock_by_path()`, now returns `(file_hash, dict[key, (value, locked)])` instead of bare `dict`
- **`FileSearchEngine.get_all_metadata()`** refactored to single-query flow; returns `(file_record, file_hash, tags_with_lock, meta_info)` 4-tuple (was 3-element list without file_hash or lock info)
- **`MetaViewerWidget`** (`wafer/app/viewer/preview/meta_panel.py`): header bar with "Add tag" (`+`) and "Reload" buttons; `tag:` prefixed sections (tag panel plugins) separated from `meta:` prefixed sections; `reload_requested` signal; `set_data()` and `clear()` now track current path/hash/db
- **`FilterRow`** (`wafer/app/viewer/widgets/search_container.py`): per-row enable/disable toggle button; disabled rows are excluded from query execution; visual dimming on disable
- **`LogPanel`** (`wafer/builtins/log_panel.py`): log colors and background now driven by `ThemeManager` palette (theme-aware); `_LogTab` emits `user_scrolled_away`/`user_scrolled_to_bottom` signals; "Auto Scroll" checkbox auto-unchecks on manual scroll-away and re-checks on scroll-to-bottom
- **Profile color palette** (`wafer/app/viewer/widgets/profile_popup.py`): "More..." button opens `ColorPickerDialog` for arbitrary custom profile colors beyond the preset swatches
- `window` icon improved with filled title-bar button; `folder_plus` padding tightened
- `TextFilter.bind_key_store()` class method removed (key store binding moved into `SearchContainer` directly)
- `FileListProvider.set_search_service()` removed; `_query_directory()` now uses `NaturalPathSort` directly

## [v0.6.4]
### Added
- **Florence-2 captioner extension** (`extensions/florence/`): singleton collector using Microsoft Florence-2 vision-language model with multi-task captioning (`<CAPTION>`, `<DETAILED_CAPTION>`, `<MORE_DETAILED_CAPTION>`), `base`/`large` variant selection, configurable `max_new_tokens`/`num_beams`, GPU/CPU fallback, idle engine unloading, and settings panel with drag-and-drop live preview — replaces BLIP captioner
- **Deferred install pipeline**: Plugin Manager no longer runs pip in-process; installs are enqueued to `extensions/.installer_queue/` and processed by the tray on next startup
- **`wafer/plugin/installer_queue.py`**: persistent JSON-backed install queue (`enqueue`/`dequeue`/`has_pending_queue`/`queued_names`)
- **`wafer/plugin/install_status.py`**: cross-process install progress reporting (`InstallStatusWriter`, `read_status`) and user cancel flag (`request_cancel`, `is_cancel_requested`)
- **`wafer/plugin/failed_installs.py`**: persistent record of failed install attempts (`mark_failed`, `failed_names`, `failure_info`)
- **`wafer/plugin/startup_install.py`** (`run_pending_installs()`): tray-side processor that drains the install queue, terminates processes holding `.packages/` files, and writes phase status
- **`wafer/plugin/badges.py`**: `ExtensionBadge` (`PREFERRED`/`HEAVY`/`EXTERNAL`) classification with `KNOWN_EXTENSIONS` registry and `badge_sort_key()` for ordering
- **`wafer/ui/install_waiter.py`** (`wait_for_install_complete`): viewer-side splash that spawns/attaches to the tray installer, polls status, and shows live log with Cancel button
- **`wafer/core/qt/tooltip.py`** (`InstantTooltipEventFilter`, `install_instant_tooltips()`): app-wide instant-tooltip event filter (opt-out via `wafer_disable_instant_tooltip` widget property)
- **`wafer/core/qt/color_utils.py`** (`mix_colors()`): linear color blending utility for badge coloring
- New themed icons `star`, `warning_triangle`, `external_link` in `wafer/core/qt/icon_engine.py`; `themed_icon()` accepts optional `color` override
- **Two-lane TaskScheduler** (`wafer/app/indexer/scheduler.py`): immediate/background queues split at `TaskPriority.SCAN` threshold on separate threads so high-priority dispatch tasks aren't blocked by long scans
- **`InstallSplash` log view + cancel button**: `show_log` / `cancel_label` constructor params; `set_message()`, `append_log()`, `replace_log()` with error/warning line colorization
- **Heavy-extension UI guards**: install confirmation dialog for `HEAVY` badge cards, warning icon next to heavy collectors in `CollectorsTab`, multi-heavy enable warning
- **`installer.install_requirements_only()` / `run_post_install()`**: install pipeline split into two callable phases; `cleanup_legacy_dirs()` removes obsolete `.pending/`/`.pip_staging/`
- **`Node.is_registered`** property; `_send_to_broker()` returns `bool` and warns once on initial registration failure
- **`AppProcess.terminate_cmd(wait=True)`**: terminate-and-wait variant used by tray/viewer restart paths
- `OrderTab.revert()` / `CollectorsTab.revert()` for in-place revert in Plugin Manager
- `_ExtensionCard` now shows a phase label, badge icon, and `Show/Hide Log` toggle with live `QPlainTextEdit` log view; visual separator between first-party and external extensions

### Changed
- **Installer simplified** (~830 → ~370 lines): removed staging-and-merge / deferred-pending / cross-extension version-negotiation machinery; `EmbeddedPython.pip_install()` installs directly into `extensions/.packages/` via `pip install --target ... --upgrade --upgrade-strategy only-if-needed` and streams stdout/stderr through `on_log`
- **Install UX inverted**: Install button enqueues and immediately marks `RESTART_REQUIRED`; Cancel dequeues. Pip and `post_install` only run in the tray at startup
- `install_extension()` / `install_requirements()` / `post_install()` accept `on_log` callback; `install_requirements()` returns plain `bool` (was tuple); `InstallResult.deferred` removed
- `_run_subprocess()` drains both stdout and stderr, forwards each pip line via `AppLogger.debug` and `on_log`; failure messages include last 2000 bytes of stderr
- **WD14 `post_install` simplified**: sequential model download; `onnxruntime-gpu` and `nvidia-cudnn-cu12` moved into `requirements.txt`. Idle engine timeout reduced from 120s to 30s
- Numpy requirement loosened to `numpy>=2,<3` in `extensions/ai_tagger` and `extensions/image`
- **Startup process model** (`main.py`): default and `--viewer` entry spawn tray, then `wait_for_install_complete()` before `load_plugins()`; `--tray` runs `run_pending_installs()` + `load_plugins()` and constructs the `QApplication`/tray icon before spawning indexer children
- Tray/viewer restart paths (`restart_tray`, `restart_all`, `MainWindow._perform_system_restart()`) use `terminate_cmd(wait=True)`; `restart_tray` auto-promotes to `restart_all` when an install is queued
- `AppProcess.base_command()` on Windows prefers `pythonw.exe`; `new_main()` and `ProcessMatcher.start_if_not_running()` apply `CREATE_NO_WINDOW`/`DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP` and `close_fds=True`
- `AppLogger._forward()` skips forwarding until the IPC node is registered; `try_put()` uses raw `logging.getLogger("AppLog")` to avoid recursion
- `PluginSettings.needs_restart()` consults `installer_queue.has_pending_queue()` (was `has_pending_packages()`)
- `ExtensionsTab` sorts cards by badge (preferred → neutral → heavy → external) with separator before external extensions; restores `RESTART_REQUIRED`/`FAILED` state from queue and failed-installs records
- ExifTool collector `_ensure_process()` stops the previous `ExifToolProcess` after starting a new one; `_extract()` extracts to a temp dir then moves into place; `ensure_exiftool()` validates both `exiftool.exe` and `exiftool_files/exiftool.pl` and repairs broken installs
- WD14 and ExifTool preview widgets load images via `image_loader_resolver.load()` + `numpy_to_qimage()` (was `QPixmap`/`QImage` directly)
- FFmpeg / Video `_run_7z()` and `wafer/_version.py` `git describe` add `CREATE_NO_WINDOW` flag on Windows (no console flash)
- `_on_revert()` in Database Manager, WD14 settings, ExifTool settings, and Plugin Manager: silent no-op when nothing changed (removed "Changes reverted" toast)
- `cleanup.bat`, `scripts/build.py`, `scripts/copy_clean_project.py` exclude/clean `.pending/` and `.pip_staging/` legacy directories
- `conftest.py` vendored-module reload now restores original modules on `ImportError`
- `pyproject.toml`: lint rules disabled for `extensions/**/lib/**` (vendored binaries)
- `main.bat` no longer pauses on non-zero exit code

### Removed
- **BLIP captioner extension** (`extensions/blip_captioner/`) — replaced by `extensions/florence/`
- Installer staging/pending machinery: `apply_pending_packages()`, `has_pending_packages()`, `_merge_or_defer()`, `_merge_dir()`, `_is_locked()`, `_remove_stale_packages()`, `_merge_requirements()`, `_collect_installed_extensions()`, `install_packages()`, `_PIP_STAGING`/`_PENDING_DIR` constants
- `InstallResult.deferred` field
- `PluginSettings.is_restart_pending()` / `set_restart_pending()` / `clear_restart_pending()` (use scope-based API)
- `ExtensionsTab.installing_changed` signal and "Don't close while installing" warning label

## [v0.6.3]
### Added
- **`SearchableMetaWidget`** (`wafer/ui/panel/searchable_meta_widget.py`): reusable metadata display widget with live search, keyword highlighting, long-value snippet extraction, and DPI-aware layout — replaces per-extension inline meta widgets
- **`wafer/ui/panel/` package**: new top-level UI panel module; `meta_viewer.py` (`CollapsibleCard`, `MetaRowWidget`) moved from `wafer/app/viewer/preview/` to `wafer/ui/panel/` for shared use by extensions
- **FFmpeg MetaPanel** (`extensions/ffmpeg/meta_panel.py`): `FFmpegMetaPanelPlugin` using `SearchableMetaWidget` for ffmpeg metadata display
- **`_ElidingLabel`** (`wafer/builtins/plugin_manager/extensions_tab.py`): auto-eliding label widget with tooltip for long extension lists in Plugin Manager rows
- **`MenuPlan.all_roots()`**: tray menu now auto-discovers all registered menu groups via `Menu.session().all_roots()` instead of hardcoded item list
- **`MenuPlan.hide()` supports prefix matching**: `hide(["File"])` now removes entire menu groups by name prefix, with non-fatal warning on missing targets (was `ValueError`)

### Changed
- **Builtin command files renamed** for consistency: `file_commands.py` → `file.py`, `grid_commands.py` → `grid.py`, `database_commands.py` → `database.py`, `debug_commands.py` → `debug.py`, `panel_commands.py` → `panel.py`, `profile_commands.py` → `profile.py`, `query_commands.py` → `query.py`, `setting_commands.py` → `setting.py`, `window_commands.py` → `window.py`, `foldertree_commands.py` → `foldertree.py`, `file_viewer.py` → `content_viewer.py`, `image_view.py` → `image_viewer.py`, `app.py` → `tools.py`
- **Profile and Window commands consolidated**: `ProfileCommands`, `WindowPanelCommands`, `WindowRestartCommands` merged into `window.py`; `ToolCommands` and `HelpCommands` moved from `app.py` to `tools.py`; `SettingCommands` separated into its own file `setting.py`
- **Tray `open_new_window` removed** from `TrayViewerCommands`; `tray.show_window` display changed to "Show/Hide Viewer"; `TrayDatabaseCommands` adds `:Database` section header
- **Tray menu built dynamically**: `TrayApp._build_menu()` uses `Menu.session().all_roots().hide(["File"]).build()` instead of a hardcoded menu item list
- **ExifTool MetaPanel refactored**: inline `_ExifToolMetaWidget` (grid-based key/value display with search) replaced by shared `SearchableMetaWidget`
- **`Dispatcher` lifecycle safety**: `_execute` slot moved to `_DispatchSignals` QObject; `invoke()` checks `shiboken6.isValid()` before emitting to prevent use-after-delete crashes; constructor accepts optional `parent` for QObject ownership
- **Grid `on_appear` timing improved**: `_promote_to_widget` now suppresses immediate `appear` notification; `GridPipeline` calls a dedicated `appear_fn` callback after widget render completes, ensuring plugins receive `on_appear` only after content is rendered
- Video `vgrid.toggle_appear_autoplay` display renamed from "Autoplay on Scroll" to "Autoplay on Appear"
- Video `PlaybackSlotManager.set_volume()` now propagates volume to `_appeared` overlays (was missing)
- `wafer/builtins/registration.py` updated for all command module renames

### Removed
- `wafer/app/viewer/preview/meta_viewer.py` (moved to `wafer/ui/panel/meta_viewer.py`)
- `_ExifToolMetaWidget` class from `extensions/exiftool/meta_panel.py` (replaced by `SearchableMetaWidget`)
- `tray.open_new_window` command (new window functionality available via `win.new_window`)

## [v0.6.2]
### Added
- **ImageLoader plugin type** (`wafer/plugin/imageloader/`): new `BaseImageLoader` base class, `ImageLoaderResolver` with `load()` / `load_pil()` resolution chain, and `image_loader_resolver` singleton — decouples raw image loading from grid rendering so collectors and other subsystems can load images without depending on Qt
- **`ImageFileLoader`** (`extensions/image/loader.py`): `BaseImageLoader` implementation using OpenCV with PIL fallback, replaces the former `ImageGridPlugin` for image loading; returns `np.ndarray` / `PIL.Image` instead of `QImage`
- **`SystemImageLoader`** (`wafer/builtins/imageloader.py`): fallback `BaseImageLoader` using `FileThumbnailer`, replaces `SystemThumbnailPlugin` (former `ImageGridPlugin` in `wafer/builtins/grid.py`)
- **WD14 Tagger Settings panel** (`extensions/ai_tagger/panel.py`): `WD14SettingsPanelPlugin` with drag-and-drop live preview, configurable thresholds (`general_threshold`, `character_threshold`), rating mode selection (top/name/all), character and tag output toggles, tag blacklist, device info display, and save with optional delete & re-collect confirmation dialog
- **`wd14_config`** (`extensions/ai_tagger/settings.py`): WD14-specific `PluginConfig` instance with default inference parameters and `parse_blacklist()` helper
- **`numpy_to_qimage()` and `pil_to_qimage()`** (`wafer/core/qt/image.py`): centralized numpy/PIL-to-QImage conversion utilities supporting Grayscale8, RGB888, RGBA8888 formats with buffer pinning
- **`CHUNK_TIMEOUT` class variable** on `BaseCollectorPlugin` and `BaseSingletonCollector` (`wafer/plugin/collector/base.py`): per-collector configurable chunk processing timeout (default 120s); `CollectorResolver.chunk_timeout()` accessor added
- **`_DeleteConfirmDialog`** (`wafer/builtins/database_manager/data_tab.py`): dedicated confirmation dialog for data deletion with re-collect checkbox, replacing inline `QMessageBox`
- **`_BlipSaveConfirmDialog`** (`extensions/blip_captioner/panel.py`): save confirmation dialog with separate delete/re-collect checkboxes
- **`_ContainImageLabel`** (`extensions/exiftool/panel.py`): auto-scaling image label widget that maintains aspect ratio on resize
- **Loading indicator** in ExifTool key browser tab via `OverlayLoadingIndicator`
- `WD14TaggerCollector.on_request()` handling `wd14.preview` and `wd14.device_info` actions for live settings panel preview
- `WD14TaggerCollector.on_notify()` reloads settings from `wd14_config` and clears caches

### Changed
- **Grid thumbnail pipeline refactored**: `GridResolver` now merges widget plugins and image loaders into a unified `resolve_merged_chain()` sorted by priority; `GridResolver.load()` delegates to `image_loader_resolver` instead of iterating `ImageGridPlugin` instances; `GridPipeline` uses merged chain for resolve dispatch
- **Collectors use `image_loader_resolver`**: `WD14TaggerCollector` and `BlipCaptionerCollector` load thumbnails via `image_loader_resolver.load_pil()` instead of `FileThumbnailer` directly
- `WD14TaggerCollector._build_tags()` now respects configurable settings: rating mode (top/name/all), enable/disable flags for rating/character/tags, and tag blacklist filtering
- `WD14TaggerCollector.process()` reads thresholds from `wd14_config` settings instead of hardcoded constants
- `PluginConfig.load()` now acquires `ini_lock` for the entire read operation (was previously unlocked)
- `BlipCaptionerCollector.CHUNK_TIMEOUT` set to 360s (heavy model inference)
- `DevLogPanel` renamed to `LogPanel`, `DevLogPanelPlugin` renamed to `LogPanelPlugin` with NAME `"log"` and DISPLAY_NAME `"Log"` (`wafer/builtins/devlog.py` → `wafer/builtins/log_panel.py`); `DEFAULT_ENABLED` changed from `DEV_MODE` to `False`
- `ImageGridPlugin` base class removed from `wafer/plugin/grid/base.py`; removed from `wafer/plugin/__init__.py` public API; `BaseImageLoader` added to public API
- BLIP Settings panel: preview auto-triggers on drop, resizable thumbnail, `Dispatcher.post()` replaces raw `threading.Thread`, save flow shows confirmation dialog with separate delete/re-collect options, added "Revert" button
- ExifTool Settings panel: "Save & Delete Data" button renamed to "Save", "Cancel" button renamed to "Revert", save skips when no changes detected, sample preview thumbnail uses `_ContainImageLabel` for responsive scaling
- Database Manager: "Cancel" button renamed to "Revert"; data deletion re-collect checkbox moved from inline to `_DeleteConfirmDialog`
- Plugin Manager: "Cancel" button renamed to "Revert"; `open_panel_btn` color changed from `success` to `accent` theme color
- `AppLogger._forward()` now forwards all log levels to remote (removed `DEV_MODE` gate and `_ALWAYS_FORWARD` filter)
- `FunctionProfiler` summary output downgraded from `info` to `debug` level
- IPC `try_put()` accepts optional `label` parameter for improved queue eviction diagnostics; all call sites updated with descriptive labels
- IPC `Broker` simplified ZMQError logging (removed `EHOSTUNREACH` filter)
- `Outbox.scan_all_outbox()` checks for `outbox` table existence before querying (prevents crash on empty/new DBs)
- Duplicate `_pil_to_qimage()` in `wafer/ui/dialogs.py` replaced with shared `pil_to_qimage()` from `wafer/core/qt/image.py`
- `_setup_faulthandler()` in `main.py` accepts `force` parameter
- Silent `except` blocks replaced with logged warnings in `BatchRenamerPlugin.save_state()`, `DatabaseManagerPlugin.save_state()`/`restore_state()`, `file_operations.py` `_rmtree_onerror()`/cut cleanup, and `installer.py` `apply_pending_packages()`
- `CollectorWorker` reads `CHUNK_TIMEOUT` from collector class via `collector_resolver.chunk_timeout()` instead of using a hardcoded constant

### Removed
- `wafer/builtins/grid.py` (`SystemThumbnailPlugin` — replaced by `SystemImageLoader` in `wafer/builtins/imageloader.py`)
- `extensions/image/grid.py` (`ImageGridPlugin` — image loading moved to `ImageFileLoader` in `extensions/image/loader.py`)
- `ImageGridPlugin` abstract base class from `wafer/plugin/grid/base.py`
- `GridResolver.resolve_chain()`, `resolve_instance()`, `resolve_image_instance()` methods (replaced by `resolve_merged_chain()`)
- Hardcoded `GENERAL_THRESHOLD` / `CHARACTER_THRESHOLD` constants from `extensions/ai_tagger/collector.py` (replaced by `wd14_config` settings)
- `_CHUNK_TIMEOUT` constant from `wafer/app/collector/worker.py` (replaced by per-collector `CHUNK_TIMEOUT` class variable)

## [v0.6.1]
### Added
- **`PluginConfig`** (`wafer/plugin/config.py`): INI-based per-plugin configuration system with typed load/save, section-scoped caching, thread-safe writes via shared `ini_lock`, and `save_and_notify()` for IPC propagation to running collectors
- **BLIP Settings panel** (`extensions/blip_captioner/panel.py`): `BlipSettingsPanelPlugin` with live preview via drag-and-drop, adjustable inference parameters (`min_length`, `max_length`, `num_beams`), device info display, and "Save & Re-collect" triggering IPC data deletion and re-collection
- **`blip_config`** (`extensions/blip_captioner/settings.py`): BLIP-specific `PluginConfig` instance with default inference parameters
- **Installation cancellation support**: `InstallerCancelled` exception and `is_cancelled` callback threaded through `_run_subprocess()`, `install_requirements()`, `install_packages()`, `install_extension()`, and all `post_install()` methods; cancel button added to Plugin Manager extension cards
- **`InstallResult` dataclass** and **`InstallState` enum** (`wafer/plugin/installer.py`): structured return types for install operations replacing bare tuples
- **`RestartScope` flag enum** (`wafer/plugin/installer.py`): granular restart scope tracking (`VIEWER`, `TRAY`, `ALL`) with `restart_scope_of()` and `restart_scope_from_plugins()` helpers
- **Deferred package installation**: locked files during install are staged in `.pending/` and applied on next startup via `apply_pending_packages()`; stale dist-info cleanup via `_remove_stale_packages()`
- **Broker-lost detection** (`wafer/core/ipc/node.py`): `Node.on_broker_lost()` callback with configurable timeout; `BROKER_LOST_TIMEOUT` (20s) constant in `transport.py`; collector, parser, and indexer processes auto-shutdown when broker becomes unreachable
- **`Node.enqueue()`** method for sending pre-built `Message` objects directly
- **IPC request/reply for collectors**: `BaseCollector.on_request()` virtual method; `CollectorWorker` handles `service.request` topic and routes replies via `msg.reply()`
- **Restart scope tracking in Plugin Manager**: `PluginSettings.restart_scope()` / `merge_restart_scope()` / `needs_restart()` methods; restart label in UI shows differentiated messages per scope (viewer / tray / both)
- `MainWindow._perform_system_restart()` and `_restart_other_viewers()` for coordinated restart on close when pending plugin changes exist
- DLL directory registration for `.libs` subdirectories in shared packages (`_setup_packages_dll_directories` in `loader.py`) for Windows native library resolution
- `setup` pytest marker for extension install smoke tests (`pyproject.toml`)

### Changed
- `BaseCollector.on_notify()` and `BaseParser.on_notify()` now accept optional `payload: dict | None` parameter; `notify_to()` forwards optional payload via IPC
- `PluginBase.post_install()` signature extended with `is_cancelled` parameter across all base classes and all extensions (`ai_tagger`, `blip_captioner`, `exiftool`, `ffmpeg`, `video`)
- `install_requirements()` and `install_packages()` return `tuple[bool, bool]` (success, deferred) instead of `bool`; `install_extension()` returns `InstallResult` dataclass instead of `tuple[bool, bool, list]`
- `_run_subprocess()` default timeout changed from 300s to 0 (no limit); supports `is_cancelled` callback for cooperative cancellation
- **`BaseFilterPlugin.SCOPE` renamed to `QUERY_SCOPE`** to avoid collision with the new `PluginBase.SCOPE` attribute (`"viewer"` default; `BaseCollector`/`BaseParser` override to `"tray"`)
- `PluginSettings._write_ini_value()` uses shared `ini_lock` from `config.py` for thread safety
- `BlipInference.predict()` accepts configurable `min_length`, `max_length`, `num_beams` keyword arguments (previously hardcoded)
- `BlipCaptionerCollector` and `WD14TaggerCollector` `post_install()` now parallelizes model download with package installation via background thread; post-install GPU/device verification removed
- Idle engine unload logging in `WD14TaggerCollector` and `BlipCaptionerCollector` moved outside the lock
- `PluginLoader.load_all()` calls `apply_pending_packages()` at startup; `get_plugin_dir()` returns normalized path
- `restart_all` command delegates to `MainWindow._perform_system_restart()` and clears restart scope
- Extensions tab uses `CardStatus` enum and `resolve_install_state()` for unified status management with installing / cancelling / deferred / restart-required states
- Plugin Manager save flow computes per-change `RestartScope` (enabled plugins → scope from plugin classes, order → viewer, collectors → tray) and shows differentiated restart messages
- `ffmpeg/parser.py` uses `encoding="utf-8", errors="replace"` instead of `text=True`; added debug logging for ffprobe failures
- `scripts/build.py`: download URLs restricted to HTTPS from allowed hosts only; empty download validation added; `.pip_staging` excluded from build output
- `WaferConsole.cs`: proper argument escaping via `EscapeArg()`; `Process` wrapped in `using` block

### Fixed
- `DirectoryFilter.SCOPE` renamed to `QUERY_SCOPE` to match the base class rename (was referencing the old attribute name)

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
