# Duplicate

Two independent parsers that both run whenever a source's `file_hash` is written.

**Full Hash** replaces the scan-time partial signature with a full content hash (BLAKE3, 64 chars). Existing tags follow the file to the new hash automatically.

**Duplicate** tags `duplicate.has_duplicate` when more than one source shares the hash, and removes it when they no longer do. Tags are stored per hash, so every file sharing it gets the flag.

Enable Full Hash for reliable duplicate detection; partial signatures can collide.
