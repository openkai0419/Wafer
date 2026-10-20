# Mapping

Shows the selected files on the database's precomputed 2D map, placed by how similar their tags, metadata, numbers, or colors are, and groups them.

- Grid: right-click → Selection → Mapping → Set / Add
- Map: the image nearest the center comes to the front and stays there. Click or drag to select. Shift/Alt adds, Ctrl+click toggles, Ctrl+drag removes. F frames the selection (or everything). Copy, cut and other file commands work like in the Grid.
- One panel with two tabs: Map shows the files you send, Settings trains the database-wide map. Thumbnails, Single/Group and Spacing (Map) are per tab; the gear settings are shared.
- Groups come from the whole database, so a group keeps its color in any selection. Settings sets them per database (Group size, Strictness, Fine groups); Subgroup size on Map splits them into smaller ones.
- Settings: choose keys and retrain the database-wide map. Enable the Mapping parser per database in Plugin Manager; it keeps new files placed in the background. Training learns from up to Training files random files with values and places the rest. Quick Train does the same on random files without saving.
- Folders compares paths by their folders (file name ignored).
- Files not placed yet (new files, files inside archives) are listed as waiting.
