# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [v0.7.4]
### Added
- Portable in-app updates: download and apply updates from the Update panel, with validation and automatic rollback on failure.
- Portable uninstaller that removes the app and optionally user data.
- `Quit All` command to close all Viewer and Tray processes together.

### Changed
- Off-screen windows, dialogs, panels, and popups are moved back onto a visible screen when restored.
- Grid AutoScroll can loop back to the start, optionally rerunning the current query.

### Fixed
- Quit, restart, and update-apply now shut down leftover processes and windows more reliably.

## [v0.7.3]
### Added
- Panel menu commands to reset the default layout and recascade floating panels.
- A dedicated Image Spread toggle and a match-size option for aligned multi-page layouts.
- An option to scroll back to the selected item after grid updates.

### Changed
- Normal navigation moves file-by-file while slideshow advances by the visible spread.
- Grid refreshes keep the current scroll position by default.
- Checkable menu entries now reflect the live UI state.

### Fixed
- Renamed files in watched folders recover more reliably.
- Restarting with a panel isolated no longer leaves panels collapsed.
- Deleting a metadata key now requires confirmation.

## [v0.7.2]
### Changed
- Viewer windows keep the correct Windows taskbar identity when opened from the launcher.
- Portable builds no longer bundle test-only files, and the root license notice points to the full license texts.

### Fixed
- Idle rescans recover missed folder changes more reliably.

## [v0.7.1]
### Changed
- Tag and metadata cards now share a searchable list with dialog-based editing, and EXIF and media metadata are editable the same way.
- Collector and parser timeouts are now configured per plugin.

### Fixed
- Heavy metadata indexing is interrupted less often.

## [v0.7.0]
### Added
- Verified downloads with SHA-256 checks for ExifTool, FFmpeg, and video dependencies.

### Changed
- Pending extension installs now run before startup completes, and duplicate install windows are prevented.
- Portable builds ship only the windowed launcher and use the bundled Python runtime for checks.

### Fixed
- File actions now reject archive members and other non-physical paths.
- Video hover playback cleans up more safely.

## [v0.6.19]
### Added
- An Update panel with manual and startup release checks, in-app release notes, download links, and skip or remind-later actions.

### Changed
- Batch Rename defaults to natural-name sorting, supports Enter or F2 to edit, and adds separate cover/contain fits for the left and right previews.
- Panels can run startup actions after the main window loads.
- Portable builds and releases now include release notes.

### Fixed
- Third-party notices are generated reliably on Windows.

## [v0.6.18]
### Added
- A built-in multi-page image viewer with configurable spreads and reading direction.

### Changed
- Archive members and other virtual files render consistently across the grid and viewer.
- Navigation and slideshow follow the active viewer's page count for multi-page spreads.
- Batch rename previews keep sort order, defer rebuilds while editing, and add restore actions.
- Plugin enable/disable choices persist more reliably across restarts.

### Fixed
- If a renderer fails to open a file, Wafer continues to the next one instead of stopping.

## [v0.6.17]
### Added
- A destination chooser when a grid drop falls back to the selected folder.

### Changed
- Refreshed the default key and mouse presets with folder navigation, mark toggles, and updated grid/viewer actions.
- Grid and folder-tree drops resolve to the nearest visible target.
- Folder-tree navigation moves between sibling folders and defers reloads while editing.
- Rename preview thumbnails load at higher detail.

### Fixed
- Drops now reject archive paths as destinations and use physical source paths.
- Folder deletions are handled correctly even when watchers mislabel them.

## [v0.6.16]
### Added
- Marks can be stored per path or per file content, with conversion between the two.
- Grid badges and overlays for marks, with visibility and size controls.
- A NOT operator for subtracting a filter's results from a search.

### Changed
- Metadata panels now use a unified scope-aware card layout.

### Fixed
- Watched-folder moves are inferred more reliably from delete/create pairs.
- Key suggestions respect subfolder and contained-file options.
- Reloading folders keeps the current scroll position.
- Plugin Manager README previews no longer error on stale updates.

## [v0.6.15]
### Added
- A color search extension: stores image palette tags and searches by color similarity, with swatches you can apply to queries.

### Changed
- Renamed the ai_tagger extension to wd14 to match the model it provides.
- New searches and saved presets now default to unsorted instead of path order.

### Fixed
- Check All and Uncheck All in the ExifTool key browser now apply only to filtered keys.

## [v0.6.14]
### Added
- A command to move to the previous or next file based on the clicked side of the viewer.

### Changed
- Opening a new viewer reserves the newest free workspace slot.
- Refreshed the default presets with shortcuts for marks, clipboard actions, binding settings, panel solo, and mouse-position navigation.
- Portable builds now ship the Japanese README and cleanup script.

## [v0.6.13]
### Changed
- Collector and parser workers now shut down cleanly before forced termination.
- Reordered the main toolbar and stopped the combo box from changing on scroll.

### Fixed
- ExifTool, ZIP, and ML collectors release background resources on shutdown.

## [v0.6.12]
### Added
- A copy/move chooser for grid and folder-tree drops, with a saved default.
- An option to decouple database refreshes from auto-executing searches.

### Changed
- Copy and move progress shows real progress, supports cancellation, and handles cross-device moves.
- Tag edits refresh marks without rerunning the whole search.

### Fixed
- Internal copy drops are accepted and drops finalize cleanly.
- Scanner updates skip unsupported files.

## [v0.6.11]
### Changed
- Changed the source license from Apache-2.0 to LGPL-2.1-or-later and updated the related docs.
- Reorganized the bundled license files.

## [v0.6.10]
### Added
- Panel solo commands to isolate a docked panel or maximize a floating one.
- Search controls for including archive members as their own list.

### Changed
- The right-side toolbar now opens the Query menu.
- Watched-folder cleanup handles renaming or removing whole source trees.

### Fixed
- Improved ZIP member handling for legacy encodings and malformed entries.
- Nested folder moves inside the watched root rename correctly.

## [0.6.9]
### Added
- A ZIP extension that indexes archive members as browsable virtual files.
- Standard file fields (path, name, size, dates, hash) now resolve directly from the database for faster queries.

### Changed
- Database schema updated for faster common queries and sorts.
- Schema changes now migrate existing data instead of dropping it.
- Renames now propagate to files inside archives.

## [v0.6.8]
### Added
- Editable metadata: add, rename, delete, and lock your own metadata keys alongside tags.
- Centralized plugin-kind labels and colors shared by the loader and Plugin Manager.
- Reusable anchored popups with screen clamping.

### Changed
- Plugin Manager badges render with consistent labels and colors.
- The metadata panel separates standard file fields from tags and metadata, and the add dialog targets tags or metadata by context.

### Fixed
- Locked metadata is preserved during collection and cleanup.
- Tag and metadata edits keep overlays and reloads in sync.

## [v0.6.7]
### Added
- A workspace system that saves and restores window state as slots and UI/path/filter presets.
- A workspace toolbar and commands for saving, applying, and managing presets.
- Recursive expand/collapse in the folder tree via Shift-click.
- App settings now sync across open viewers.

### Changed
- Replaced profiles with workspace slots; the viewer now uses slots for restore.
- Search rows support enable/disable, reorder, and insert actions.
- Plugin UI state is saved and restored more consistently.

### Fixed
- Tag edits refresh the current search so marks and overlays stay in sync.

### Removed
- The old profile and bookmark storage, replaced by workspace slots and presets.

## [v0.6.6]
### Added
- A shared dialog for viewing full metadata values, with copy actions.

### Changed
- Tag-key lookups support full-database and path-restricted fetches.
- Mark overlays reload from a whole-database cache and ignore stale results.

## [v0.6.5]
### Added
- A mark system: user-defined named, colored marks with grid badges, filtering, and a side-panel toggle.
- Inline tag editing in the metadata panel: add, delete, rename, and lock tags.
- A custom color picker with recent colors.

### Changed
- User-locked tags are preserved during collection.
- The metadata panel adds tag and reload actions and separates tags from metadata.
- The log panel is now theme-aware with smarter auto-scroll.

## [v0.6.4]
### Added
- A Florence-2 captioner extension with multiple caption modes and settings, replacing the BLIP captioner.
- Extension installs now run at startup from a queue instead of in-process, with progress, cancel, and failure tracking.
- Install confirmation and warnings for heavy extensions.

### Changed
- Simplified the installer and inverted install UX: installs are queued and applied at startup.
- Startup spawns the tray first, then loads plugins after installs complete.
- Restart paths now wait for clean process termination.

### Removed
- The BLIP captioner extension, replaced by Florence-2.

## [v0.6.3]
### Added
- A reusable searchable metadata widget with live search and highlighting, shared by extensions.
- The tray menu now auto-discovers all registered menu groups.

### Changed
- Renamed builtin command files for consistency and consolidated related commands.
- The tray menu is built dynamically instead of from a fixed list.
- Grid on-appear callbacks fire only after content is rendered.

### Removed
- Redundant per-extension metadata widgets, replaced by the shared one.

## [v0.6.2]
### Added
- An image-loader plugin type so images can be loaded without depending on Qt.
- A WD14 Tagger settings panel with live preview and configurable thresholds.

### Changed
- The grid thumbnail pipeline now merges widget plugins and image loaders by priority.
- WD14 tagging respects configurable thresholds, rating mode, and a blacklist.
- Renamed the Dev Log panel to Log.

### Removed
- The old per-type thumbnail plugins, replaced by the image-loader system.

## [v0.6.1]
### Added
- Per-plugin INI configuration with live propagation to running collectors.
- A BLIP settings panel with live preview and adjustable parameters.
- Cancellable installs with a cancel button in Plugin Manager.
- Automatic shutdown of background processes when the broker becomes unreachable.

### Changed
- Collector and parser notifications can carry a payload.
- Restart scope is tracked per change, showing whether the viewer, tray, or both need to restart.
- Model downloads now run alongside package installation.

### Fixed
- Corrected a filter scope attribute name.

## [v0.6.0]
### Added
- A portable build system that bundles Python and C# launchers instead of PyInstaller.
- Extension requirements now pin shared dependencies per extension.

### Changed
- Rewrote the plugin installer to use a single shared packages directory with conflict resolution.
- Simplified path and version handling for portable builds.

### Removed
- The PyInstaller build setup.

## [v0.5.9]
### Added
- A BLIP captioner extension for generating image captions, with GPU/CPU fallback and caching.
- Optional crash logging via an environment variable.
- Automatic cleanup of outdated embedded Python runtimes.

### Changed
- Renamed "Detacher" to "Parser" throughout.
- Upgraded the embedded Python to 3.11 and raised the minimum version to 3.11.
- Keep the 5 most recent logs.

### Removed
- The old detacher packages, replaced by parser.

## [v0.5.8]
### Added
- Restart commands (all, tray, viewer) under the Window menu.

### Changed
- Reorganized the tray menu into Viewer, Database, Window, and Tray groups.
- Moved Help (README, About) into its own menu group.

### Fixed
- Plugin Manager collectors tab refreshes on open and preserves state.
- Corrected README release links.

## [v0.5.7]
### Added
- New databases seed enabled collectors from global defaults.
- Multi-select ignore, copy/paste, and multi-delete for path lists in Database Manager.

### Changed
- Renamed "Purge" to "Delete" across the UI and internals.
- Database creation now runs in the background.

### Fixed
- Plugin installer now works in packaged builds.
- Video viewer loop default.

## [v0.5.6] - 2026-04-12
### Changed
- README formatting and content updates

## [v0.5.5] - 2026-04-12
### Changed
- GitHub Actions `build.yml` workflow configuration updates

## [v0.5.4] - 2026-04-12
### Fixed
- Minor code and tooling fixes across dialogs, metadata panels, and build scripts.

## [v0.5.3] - 2026-04-12
### Added
- ExifTool and FFmpeg extensions with auto-downloaders.
- A ComfyUI metadata parser.
- A metadata panel plugin system.
- A profile system with JSON persistence.
- A database data tab for per-prefix inspection and cleanup.
- A Markdown viewer and a metadata key browser.

### Changed
- Renamed Session to Profile throughout.
- Reorganized UI code into a top-level UI package.
- Image EXIF extraction now goes through the ExifTool extension.

### Removed
- The old session storage, replaced by profiles.

## [v0.5.2] - 2026-04-06
### Added
- Version management.

## [v0.5.1] - 2026-04-06
- Initial public release.
- Core viewer with grid, image/video preview, and file viewer.
- Plugin architecture with auto-discovery.
- SQLite metadata database with background indexing.
- Multi-process IPC.
- Command and key/mouse binding system.
- Bundled extensions: image, animated, video, wd14, filters, layouts, prompt parser.
- Batch renamer with preview.
- Theme and translation support.
