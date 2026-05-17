# Release Notes

User-facing highlights for each Wafer release. These notes are shown in the Update panel and used as the GitHub Release body.

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