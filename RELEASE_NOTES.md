# Release Notes

User-facing highlights for each Wafer release. These notes are shown in the Update panel and used as the GitHub Release body.

## [v0.7.1]

This release refreshes metadata browsing and improves stability for long-running metadata indexing.

### Highlights
- Metadata sections now share a searchable card layout with a unified edit dialog, making tag and metadata changes easier to browse and update.
- EXIF and media metadata now follow the same editable workflow as other metadata cards, so the side panel behaves more consistently across extensions.

### Improvements
- Long-running metadata extraction and AI parsing now use extension-specific worker limits and timeout windows, which reduces premature interruptions during heavier indexing jobs.

### Fixes
- Background maintenance now waits more carefully for active metadata workers, reducing idle-time interference while larger indexing tasks are still running.

## [v0.7.0]

This release focuses on install reliability and safety fixes.

### Highlights
- Dependency downloads are safer and more reliable.
- Pending extension installs now finish more cleanly at startup.

### Fixes
- File actions now reject archive members and other non-physical paths.
- Video hover playback cleans up idle timers more safely.

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