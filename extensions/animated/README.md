## Animated Extension

Frame-by-frame playback for animated image formats.

### Supported Formats
GIF, APNG, WebP (animated)

### Features
- **Frame Playback** — Automatic animation with frame caching
- **Grid Thumbnails** — Animated preview in grid view
- **Auto Detection** — Only activates when the file is actually animated; static files fall through to the `image` extension

### Cache Limit
`Widgets > Animated > Cache Limit...` sets how much memory decoded frames may use, for the Grid and the Viewer separately, in each Viewer window. The default is 2560 MiB. They also keep at most 128 (Grid) and 8 (Viewer) files. A file larger than the limit plays without being cached.
