# Release Notes

User-facing highlights for each Wafer release. These notes are shown in the Update panel and used as the GitHub Release body.

## [v0.7.0]

This release makes extension setup more reliable, tightens file-operation safety around archive contents, and smooths a few startup and video playback edge cases.

### Highlights
- Automatic downloads for ExifTool, FFmpeg, and video playback dependencies now verify SHA-256 checksums before installation, and FFmpeg or mpv downloads follow the latest upstream release instead of fixed bundled archives.
- Pending extension installs now finish before the tray completes startup, and the install progress UI avoids opening duplicate waiter windows.

### Improvements
- Portable packages now use the bundled Python runtime directly for command-line checks and keep bundled third-party notices aligned with the shipped runtime dependencies.

### Fixes
- File actions now stop invalid open, reveal, create-folder, copy, move, and paste attempts against archive members and other non-physical paths.
- Video hover playback now replaces and cancels idle timers safely, reducing cleanup races after rapid pointer movement or shutdown.

## [v0.6.19]

This release adds in-app update notifications and makes batch rename previews easier to work with.

### Highlights
- Added an Update panel that can check the latest GitHub release, show release notes inside Wafer, and open the download page directly.
- Wafer can now check for updates automatically on startup, with options to skip notifications for the current version or dismiss them until later.

### Improvements
- Batch Rename now opens file lists in natural name order, lets you start editing the selected cell with Enter or F2, and adds separate cover or contain controls for the left and right thumbnail previews.

### Notes
- Portable packages now include release notes so update details remain available even when the app falls back to bundled notes instead of a live download.

## [v0.6.18]

This release improves image viewing, archive rendering, batch rename editing, and plugin state handling.

### Highlights
- Added a built-in multi-page image viewer with configurable spreads and reading direction.
- ZIP members and other virtual files now render more consistently across the grid and file viewer.
- Batch rename editing now keeps its table steadier while you work, including selected-cell edits and restore actions.
- Plugin enable and disable choices are saved more predictably across restarts.

### Fixes
- If one renderer cannot resolve a file, Wafer now continues to the next available renderer instead of stopping the whole display flow.

### Notes
- Some plugin changes may still require a restart, but the restart prompt now follows the plugins that actually changed.