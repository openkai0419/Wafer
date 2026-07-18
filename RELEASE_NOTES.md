# Release Notes

User-facing highlights for each Wafer release. These notes are shown in the Update panel and used as the GitHub Release body.

## [v0.7.4]

### Highlights
- Portable builds can now download updates in the Update panel, follow progress, and apply them after restart.
- Portable builds now include an uninstaller that removes the app and can also remove your data.

### Improvements
- A new Quit All command closes every Viewer and the Tray together.
- Restored windows and popups that would open off-screen are now moved back into view.
- AutoScroll can now loop back to the top and optionally rerun the current query.

### Fixes
- Quit, restart, and update installs now close leftover windows and background processes more reliably.

## [v0.7.3]

### Highlights
- Image Spread now has its own toggle and can keep visible pages the same size for easier multi-page viewing.
- Panel menus now include quick actions to reset the whole layout or floating panel positions.

### Improvements
- Normal navigation now moves file-by-file while slideshow advances by the visible spread.
- Grid refreshes keep your scroll position by default; an option can scroll to the selected item instead.

### Fixes
- Renamed files in watched folders recover in the database more reliably.
- Restarting with a panel isolated no longer leaves the layout collapsed.
- Deleting a metadata key now asks for confirmation.

## [v0.7.2]

### Improvements
- Viewer windows keep the correct Windows taskbar identity for consistent grouping and relaunch.
- Portable packages no longer include test-only files.

### Fixes
- Idle rescans recover missed folder changes more reliably.

## [v0.7.1]

### Highlights
- Metadata sections now share a searchable card layout with a unified edit dialog.
- EXIF and media metadata are now editable like other metadata cards.

### Fixes
- Long-running metadata indexing is interrupted less often.

## [v0.7.0]

### Highlights
- Dependency downloads are safer and more reliable.
- Pending extension installs finish more cleanly at startup.

### Fixes
- File actions now reject archive members and other non-physical paths.
- Video hover playback cleans up more safely.

## [v0.6.19]

### Highlights
- Added an Update panel to check the latest release, read notes in-app, and open the download page.
- Wafer can check for updates on startup, with options to skip or remind later.

### Improvements
- Batch Rename opens in natural name order, starts editing with Enter or F2, and adds separate fit controls for the left and right previews.

## [v0.6.18]

### Highlights
- Added a built-in multi-page image viewer with configurable spreads and reading direction.
- Archive members and other virtual files render more consistently.
- Batch rename editing stays steadier while you work.
- Plugin enable/disable choices are saved more reliably across restarts.

### Fixes
- If one renderer can't open a file, Wafer now tries the next one instead of stopping.