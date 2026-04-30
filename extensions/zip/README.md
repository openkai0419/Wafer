# Zip extension

Zip support is implemented as normal Wafer plugins: Collector, Grid, and Viewer.

- The collector expands one `.zip` source into many logical child rows.
- Child logical paths use `archive.zip::member/path.ext` (separator: `VIRTUAL_PATH_SEPARATOR`).
- Rendering materializes the child into the Zip extension cache and delegates the real path back to normal Wafer plugin resolution.
- The Zip extension does not classify child formats. Images, videos, animated files, and system thumbnail fallback are selected by existing plugins after materialization.

## Limitations (MVP)

- **In-archive file operations target the parent `.zip` file.** Selecting an in-archive entry and invoking `Delete` / `Copy` / `Cut` / `Rename` / `BatchRename` / `PasteHere` / `OS Shell Menu` operates on the whole parent archive (not on the individual entry). This is intentional for MVP and is enforced by the file command layer (`source` resolves to the parent archive for virtual paths).
- To delete or rename an in-archive entry, modify the `.zip` externally and re-collect.
- Future versions may add in-archive write support, but it is out of scope for the current release.
