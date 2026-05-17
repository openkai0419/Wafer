# Release Notes

User-facing highlights for each Wafer release. These notes are shown in the Update panel and used as the GitHub Release body.

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